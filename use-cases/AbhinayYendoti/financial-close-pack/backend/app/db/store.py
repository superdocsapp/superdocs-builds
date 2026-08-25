"""Persistence, on SQLite or PostgreSQL.

Both backends store the same thing: one JSON document per close and per job. The close
is read-modify-written as a whole under a lock, so the schema stays deliberately dumb
and the domain logic never has to think about columns.

`DATABASE_URL` selects the driver. `postgresql://` (Neon and friends) uses psycopg3;
`sqlite:///` uses the stdlib driver, which is what the test suite runs on. The two
differ in three details, all handled here rather than by the callers:

  * placeholders  - sqlite takes `?`, postgres takes `%s`
  * row access    - sqlite has `Row`, psycopg needs `dict_row`
  * write locking - sqlite serialises writers with BEGIN IMMEDIATE, postgres takes a
                    row-level `SELECT ... FOR UPDATE` inside the transaction

Read-modify-write goes through `mutate_close`, which holds the lock for the whole
callback so concurrent decisions cannot clobber each other on either backend.
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from ..core.config import settings

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS closes (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    close_id    TEXT NOT NULL,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_close_id ON jobs (close_id);
"""

# jsonb, not text: it is the same read-modify-write from Python's side, but it lets an
# operator query into a close in psql without parsing it out first.
POSTGRES_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS closes (
        id          TEXT PRIMARY KEY,
        data        JSONB NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jobs (
        id          TEXT PRIMARY KEY,
        close_id    TEXT NOT NULL,
        data        JSONB NOT NULL,
        updated_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS jobs_close_id ON jobs (close_id)",
)


def _is_postgres() -> bool:
    return settings.is_postgres


def _ph(sql: str) -> str:
    """Statements are written inline with sqlite's `?`; translate for psycopg."""
    return sql.replace("?", "%s") if _is_postgres() else sql


def _loads(value: Any) -> dict[str, Any]:
    # psycopg decodes jsonb into a dict already; sqlite hands back the raw text.
    return value if isinstance(value, dict) else json.loads(value)


def _dumps(value: dict[str, Any]) -> Any:
    if _is_postgres():
        from psycopg.types.json import Jsonb

        return Jsonb(value)
    return json.dumps(value)


def _db_path() -> Path:
    path = Path(settings.sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


_pool: Any = None


def _postgres_pool() -> Any:
    """A process-wide connection pool for Postgres.

    Opening a connection per query was costing ~1,890ms of TCP, TLS and auth handshake
    against a remote Neon instance, while the query itself took ~309ms - so 86% of every
    database call was spent getting to the database. Connections are now made once and
    reused.

    `min_size=1` keeps a warm connection so the first request after an idle spell does
    not pay the handshake either.
    """
    global _pool
    if _pool is None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        _pool = ConnectionPool(
            settings.resolved_database_url,
            min_size=1,
            max_size=10,
            timeout=30,
            max_idle=300,
            # autocommit so the explicit BEGIN in `_write_transaction` is the only
            # transaction in play, matching the sqlite path's isolation_level=None.
            # Autocommit, so a read costs exactly one round trip. Writes wrap themselves
            # in `connection.transaction()` below, which psycopg opens implicitly with the
            # first statement - the explicit BEGIN this replaced was a round trip that
            # bought nothing. Making the pool non-autocommit instead would have put a
            # COMMIT on every read, which measured twice as slow.
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
    return _pool


def _connect() -> Any:
    """A raw connection. Prefer `_lease()`; this exists for schema setup only."""
    if _is_postgres():
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            settings.resolved_database_url, row_factory=dict_row, autocommit=True, connect_timeout=30
        )

    connection = sqlite3.connect(_db_path(), timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def _lease() -> Iterator[Any]:
    """Borrow a connection for the duration of one operation.

    Postgres connections come from the pool and are returned, not closed. SQLite is a
    local file with no handshake to amortise, so it keeps the open/close pattern.
    """
    if _is_postgres():
        with _postgres_pool().connection() as connection:
            yield connection
        return

    connection = _connect()
    try:
        yield connection
    finally:
        connection.close()


def close_pool() -> None:
    """Release pooled connections. Called on shutdown and between test runs."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def init_db() -> None:
    connection = _connect()
    try:
        if _is_postgres():
            for statement in POSTGRES_SCHEMA:
                connection.execute(statement)
        else:
            connection.executescript(SQLITE_SCHEMA)
    finally:
        connection.close()


@contextmanager
def _write_transaction() -> Iterator[Any]:
    if _is_postgres():
        # psycopg owns the transaction: BEGIN rides along with the first statement and
        # COMMIT (or ROLLBACK) closes it, so a mutation is SELECT + UPDATE + COMMIT.
        with _lease() as connection, connection.transaction():
            yield connection
        return

    with _lease() as connection:
        try:
            # BEGIN IMMEDIATE takes sqlite's write lock up front rather than at first
            # write, so two writers cannot both read, then both try to upgrade, and
            # deadlock.
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise


def _fetchone(connection: Any, sql: str, params: tuple) -> Any:
    return connection.execute(_ph(sql), params).fetchone()


def _now() -> str:
    from ..services.clock import now_iso

    return now_iso()


def list_closes() -> list[dict[str, Any]]:
    with _lease() as connection:
        rows = connection.execute("SELECT data FROM closes ORDER BY updated_at DESC").fetchall()
    return [_loads(row["data"]) for row in rows]


def get_close(close_id: str) -> dict[str, Any] | None:
    with _lease() as connection:
        row = _fetchone(connection, "SELECT data FROM closes WHERE id = ?", (close_id,))
    return _loads(row["data"]) if row else None


def save_close(close: dict[str, Any]) -> dict[str, Any]:
    with _write_transaction() as connection:
        connection.execute(
            _ph(
                "INSERT INTO closes (id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at"
            ),
            (close["id"], _dumps(close), _now()),
        )
    return close


def mutate_close(close_id: str, mutator: Callable[[dict[str, Any]], Any]) -> tuple[dict[str, Any], Any]:
    """Apply `mutator` to a close inside a single write transaction.

    Returns (close, mutator_result). Raises KeyError if the close does not exist.
    """
    with _write_transaction() as connection:
        # FOR UPDATE gives postgres the same guarantee BEGIN IMMEDIATE gives sqlite:
        # nobody else can read-modify-write this close until we commit.
        select = "SELECT data FROM closes WHERE id = ?" + (" FOR UPDATE" if _is_postgres() else "")
        row = _fetchone(connection, select, (close_id,))
        if row is None:
            raise KeyError(close_id)
        close = _loads(row["data"])
        result = mutator(close)
        connection.execute(
            _ph("UPDATE closes SET data = ?, updated_at = ? WHERE id = ?"),
            (_dumps(close), _now(), close_id),
        )
    return close, result


def close_exists(close_id: str) -> bool:
    with _lease() as connection:
        row = _fetchone(connection, "SELECT 1 FROM closes WHERE id = ?", (close_id,))
    return row is not None


def save_job(job: dict[str, Any]) -> dict[str, Any]:
    with _write_transaction() as connection:
        connection.execute(
            _ph(
                "INSERT INTO jobs (id, close_id, data, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at"
            ),
            (job["id"], job["close_id"], _dumps(job), _now()),
        )
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lease() as connection:
        row = _fetchone(connection, "SELECT data FROM jobs WHERE id = ?", (job_id,))
    return _loads(row["data"]) if row else None


def active_job_for_close(close_id: str) -> dict[str, Any] | None:
    with _lease() as connection:
        rows = connection.execute(
            _ph("SELECT data FROM jobs WHERE close_id = ? ORDER BY updated_at DESC"), (close_id,)
        ).fetchall()
    for row in rows:
        job = _loads(row["data"])
        if job.get("status") == "RUNNING":
            return job
    return None


def prune_jobs(keep_last: int = 200) -> None:
    """Bound the jobs table; the old in-memory JOBS dict grew forever."""
    # Postgres will not accept LIMIT inside an IN-subquery without a derived table.
    sql = (
        "DELETE FROM jobs WHERE id NOT IN "
        "(SELECT id FROM (SELECT id FROM jobs ORDER BY updated_at DESC LIMIT ?) AS keep)"
        if _is_postgres()
        else "DELETE FROM jobs WHERE id NOT IN "
        "(SELECT id FROM jobs ORDER BY updated_at DESC LIMIT ?)"
    )
    with _write_transaction() as connection:
        connection.execute(_ph(sql), (keep_last,))


def reset_for_tests() -> None:
    # A pool left open across a settings change would hand out connections to the
    # previous database. Tests run on sqlite, but this keeps the invariant explicit.
    close_pool()
    with _write_transaction() as connection:
        connection.execute("DELETE FROM closes")
        connection.execute("DELETE FROM jobs")
