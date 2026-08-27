"""Durable persistence for review rounds.

A review round outlives the process: it is exported to Word, waits days for a reviewer, then
resumes. So it lives in a store, not memory. The :class:`Store` protocol has two real backends —
SQLite (zero-infra, the keyless test suite and a single-tenant deployment) and Postgres (the
multi-tenant/traffic substrate) — chosen by ``DATABASE_URL``. Swapping is configuration, not a
rewrite. Each round is its own row, so concurrent rounds are isolated by construction; writes are
transactional and last-writer-wins per round (the write-back worker adds a claim in F5).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Protocol, runtime_checkable

from notion_review.domain import ReviewRound

_DDL = """
CREATE TABLE IF NOT EXISTS review_rounds (
    id             TEXT PRIMARY KEY,
    notion_page_id TEXT NOT NULL,
    status         TEXT NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    updated_at     TEXT NOT NULL,
    data           {json_type} NOT NULL
)
"""


class RoundConflictError(RuntimeError):
    """A round was written from a stale copy — another worker updated it first.

    The write is refused rather than silently overwriting the other worker's update, so
    concurrent work on one round can never corrupt or lose state.
    """


@runtime_checkable
class Store(Protocol):
    def save(self, round_: ReviewRound) -> None:
        """Insert or update a round (upsert), keyed by id."""
        ...

    def get(self, round_id: str) -> ReviewRound | None: ...

    def list_ids(self) -> list[str]: ...

    def delete(self, round_id: str) -> None: ...

    def close(self) -> None: ...


class SQLiteStore:
    """Thread-safe SQLite backend (WAL for file paths). Default for keyless tests and demo."""

    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        if path != ":memory:":
            # A store under a directory that does not exist yet is a confusing "unable to open
            # database file"; create the directory instead of making the caller do it.
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            # Deliberately NOT write-ahead logging. WAL keeps committed data in a side file
            # coordinated through shared memory, and that coordination is not reliable on the
            # bind mounts this runs on: a second connection can conclude it is the last one and
            # delete the -wal out from under a live writer, discarding committed rounds without
            # an error anywhere. I hit exactly that. The rollback journal has no side files to
            # lose, which trades some write concurrency for the store actually being durable —
            # and concurrency is what the Postgres backend is for.
            self._conn.execute("PRAGMA journal_mode=DELETE")
            self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute(_DDL.format(json_type="TEXT"))
        # Migrate a store created before the version column existed.
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(review_rounds)")}
        if "version" not in columns:
            self._conn.execute(
                "ALTER TABLE review_rounds ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
            )
        self._conn.commit()

    def save(self, round_: ReviewRound) -> None:
        round_.touch()
        with self._lock:
            row = self._conn.execute(
                "SELECT version FROM review_rounds WHERE id = ?", (round_.id,)
            ).fetchone()
            if row is None:
                round_.version = 1
                self._conn.execute(
                    "INSERT INTO review_rounds "
                    "(id, notion_page_id, status, version, updated_at, data) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        round_.id,
                        round_.notion_page_id,
                        round_.status.value,
                        round_.version,
                        round_.updated_at.isoformat(),
                        round_.model_dump_json(),
                    ),
                )
            else:
                if row["version"] != round_.version:
                    raise RoundConflictError(
                        f"round {round_.id} changed underneath this write "
                        f"(expected v{round_.version}, found v{row['version']})"
                    )
                expected = round_.version
                round_.version = expected + 1
                cursor = self._conn.execute(
                    "UPDATE review_rounds "
                    "SET status=?, version=?, updated_at=?, data=? WHERE id=? AND version=?",
                    (
                        round_.status.value,
                        round_.version,
                        round_.updated_at.isoformat(),
                        round_.model_dump_json(),
                        round_.id,
                        expected,
                    ),
                )
                if cursor.rowcount != 1:  # lost the race between SELECT and UPDATE
                    round_.version = expected
                    raise RoundConflictError(f"round {round_.id} changed underneath this write")
            self._conn.commit()

    def get(self, round_id: str) -> ReviewRound | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM review_rounds WHERE id = ?", (round_id,)
            ).fetchone()
        return ReviewRound.model_validate_json(row["data"]) if row else None

    def list_ids(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT id FROM review_rounds ORDER BY updated_at").fetchall()
        return [r["id"] for r in rows]

    def delete(self, round_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM review_rounds WHERE id = ?", (round_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class PostgresStore:
    """Postgres backend — the multi-tenant/traffic substrate, pooled for concurrent workers."""

    def __init__(self, dsn: str) -> None:
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(dsn, min_size=1, max_size=8, open=True)
        with self._pool.connection() as conn:
            conn.execute(_DDL.format(json_type="JSONB"))
            conn.execute(
                "ALTER TABLE review_rounds ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL "
                "DEFAULT 1"
            )

    def save(self, round_: ReviewRound) -> None:
        round_.touch()
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT version FROM review_rounds WHERE id = %s", (round_.id,)
            ).fetchone()
            if row is None:
                round_.version = 1
                conn.execute(
                    "INSERT INTO review_rounds "
                    "(id, notion_page_id, status, version, updated_at, data) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        round_.id,
                        round_.notion_page_id,
                        round_.status.value,
                        round_.version,
                        round_.updated_at.isoformat(),
                        round_.model_dump_json(),
                    ),
                )
                return
            if row[0] != round_.version:
                raise RoundConflictError(
                    f"round {round_.id} changed underneath this write "
                    f"(expected v{round_.version}, found v{row[0]})"
                )
            expected = round_.version
            round_.version = expected + 1
            cursor = conn.execute(
                "UPDATE review_rounds "
                "SET status=%s, version=%s, updated_at=%s, data=%s WHERE id=%s AND version=%s",
                (
                    round_.status.value,
                    round_.version,
                    round_.updated_at.isoformat(),
                    round_.model_dump_json(),
                    round_.id,
                    expected,
                ),
            )
            if cursor.rowcount != 1:
                round_.version = expected
                raise RoundConflictError(f"round {round_.id} changed underneath this write")

    def get(self, round_id: str) -> ReviewRound | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT data FROM review_rounds WHERE id = %s", (round_id,)
            ).fetchone()
        if row is None:
            return None
        return ReviewRound.model_validate(row[0])

    def list_ids(self) -> list[str]:
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT id FROM review_rounds ORDER BY updated_at").fetchall()
        return [r[0] for r in rows]

    def delete(self, round_id: str) -> None:
        with self._pool.connection() as conn:
            conn.execute("DELETE FROM review_rounds WHERE id = %s", (round_id,))

    def close(self) -> None:
        self._pool.close()


def open_store(database_url: str | None) -> Store:
    """Pick a backend from config: Postgres when a DSN is given, else in-memory SQLite."""
    if database_url and database_url.startswith(("postgres://", "postgresql://")):
        return PostgresStore(database_url)
    if database_url:  # a sqlite file path
        return SQLiteStore(database_url)
    return SQLiteStore(":memory:")
