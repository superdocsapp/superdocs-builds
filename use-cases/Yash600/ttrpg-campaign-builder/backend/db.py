"""
db.py -- Postgres wiring.

Default path: embedded Postgres via `pgserver` (pip install pgserver).
This is real PostgreSQL 16 -- not SQLite -- running as a child process
against a local data directory, with zero Docker and zero root required.

Override path: set DATABASE_URL in .env to point at any real Postgres
server (e.g. a docker-compose instance, RDS, Supabase, etc.) and this
module skips pgserver entirely. The models and every query in this project
are plain SQLModel/SQLAlchemy -- nothing here is pgserver-specific.

Identical wiring to the healthcare-privacy-pack build (this project is
intentionally self-contained rather than importing a shared package --
see README for why), just pointed at a different default data directory
and env var names so the two builds never collide if run side by side on
the same machine.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel, Session
from dotenv import load_dotenv

load_dotenv()


def _clean_stale_postmaster_lock(pgdata_dir: Path) -> None:
    """
    Defensive cleanup for a known pgserver + ephemeral-container failure mode:
    if the process that last held pgdata_dir was killed abruptly rather than
    shut down cleanly, postmaster.pid survives with the old PID still written
    in it. On the next start, pgserver reads that file and asks the OS "is
    this PID alive" -- in a short-lived container, PIDs get reused fast, so a
    live-but-unrelated process can wrongly look like "yes, postgres is still
    running", after which pgserver skips starting a new server and every real
    connection then fails with "Connection refused" against a socket nothing
    is listening on.

    We only ever remove the lock file when we can positively confirm it's
    stale: the PID it names is not currently running a postgres process at
    all. If a real postgres happens to be up, this is a no-op.
    """
    pid_file = pgdata_dir / "postmaster.pid"
    if not pid_file.exists():
        return

    try:
        lines = pid_file.read_text().splitlines()
        pid = int(lines[0].strip())
    except (ValueError, IndexError, OSError):
        return

    proc_comm = Path(f"/proc/{pid}/comm")
    is_really_postgres = False
    if proc_comm.exists():
        try:
            is_really_postgres = "postgres" in proc_comm.read_text().lower()
        except OSError:
            is_really_postgres = False

    if not is_really_postgres:
        for name in ("postmaster.pid", "postmaster.opts", ".s.PGSQL.5432", ".s.PGSQL.5432.lock"):
            stale = pgdata_dir / name
            if stale.exists():
                stale.unlink(missing_ok=True)


# Deliberately NOT inside the project directory -- see the identical note in
# the healthcare build's db.py. $HOME (or $PGDATA_DIR override) is a plain
# local filesystem in every environment we've tested against; network/
# virtual-mounted project trees corrupt pgserver's lock file handling.
_PGDATA_DIR = Path(os.environ.get("PGDATA_DIR", str(Path.home() / ".shattered_crown_campaigns" / "pgdata")))

_engine = None
_pgserver_instance = None


def _to_sqlalchemy_uri(raw_uri: str) -> str:
    """pgserver returns a bare postgresql:// URI; SQLAlchemy needs the +psycopg2 dialect."""
    if raw_uri.startswith("postgresql://"):
        return raw_uri.replace("postgresql://", "postgresql+psycopg2://", 1)
    return raw_uri


def get_engine():
    global _engine, _pgserver_instance

    if _engine is not None:
        return _engine

    explicit_url = os.environ.get("DATABASE_URL", "").strip()

    # Explicit URL pointing at a *real* external Postgres server (not our own
    # .env.example placeholder) wins.
    use_pgserver = (
        not explicit_url
        or "localhost:5432" in explicit_url  # our own .env.example default placeholder
    )

    if use_pgserver:
        import pgserver

        _PGDATA_DIR.mkdir(parents=True, exist_ok=True)
        _clean_stale_postmaster_lock(_PGDATA_DIR)
        _pgserver_instance = pgserver.get_server(str(_PGDATA_DIR))
        sa_uri = _to_sqlalchemy_uri(_pgserver_instance.get_uri())
    else:
        sa_uri = explicit_url
        if sa_uri.startswith("postgresql://"):
            sa_uri = _to_sqlalchemy_uri(sa_uri)

    _engine = create_engine(sa_uri, echo=False)
    return _engine


def _auto_add_missing_columns(engine) -> None:
    """
    create_all() only creates tables that don't exist yet -- it never alters
    a table that already exists to match a model that's since gained a
    field. pgserver's data directory is a real, persistent Postgres data
    dir on disk, so every time a model here has grown a new column during
    development, anyone with an already-initialized local DB gets an
    UndefinedColumn error on the very next query, with no automatic way to
    recover short of deleting their whole database.

    Rather than pulling in a full migration tool for a project at this
    stage, this does the minimal safe thing on every startup: for every
    column SQLModel's metadata knows about that isn't present in the live
    table yet, ADD COLUMN it (always nullable -- existing rows get NULL,
    since there's no way to know what an old row's value "should" be).
    Never drops or alters an existing column, only ever adds new ones, and
    a failure on one column is logged and skipped rather than aborting
    startup or the columns after it.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # brand-new table -- create_all() just created it in full
        existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            try:
                with engine.begin() as conn:
                    # Native Postgres ENUM columns need their CREATE TYPE run
                    # before they can be referenced in an ADD COLUMN -- plain
                    # column types (str/int/etc) don't have this method at all.
                    if hasattr(column.type, "create"):
                        column.type.create(conn, checkfirst=True)
                    col_type = column.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                print(f"[db] auto-migrated: added column {table.name}.{column.name} ({col_type})")
            except Exception as e:
                print(f"[db] WARNING: could not auto-add {table.name}.{column.name}: {e}")


def _auto_add_missing_enum_values(engine) -> None:
    """
    Companion to _auto_add_missing_columns, covering a drift case that one
    does NOT: a *column* can already exist while the underlying Postgres
    ENUM TYPE is still missing a value that's since been added to a Python
    enum (e.g. ChangeEventType growing a new member like "document_saved").
    ADD COLUMN never runs for that case since the column is already there --
    this is the exact "LookupError: 'X' is not among the defined enum
    values" class of drift that has bitten this project before.

    For every native Postgres ENUM type SQLModel's metadata knows about,
    diff its Python members against the live pg_enum labels and run
    ALTER TYPE ... ADD VALUE IF NOT EXISTS for whatever's missing. Postgres
    has no failure mode here for a value that already exists, and this
    never renames or removes a label -- same purely-additive guarantee as
    _auto_add_missing_columns. ALTER TYPE ADD VALUE cannot run inside a
    multi-statement transaction block, so each one runs on its own
    autocommit connection.
    """
    inspector = inspect(engine)
    try:
        existing_enum_types = {e["name"]: set(e["labels"]) for e in inspector.get_enums()}
    except NotImplementedError:
        return  # dialect has no native enum introspection (e.g. non-Postgres) -- nothing to do

    seen_types: set[str] = set()
    for table in SQLModel.metadata.sorted_tables:
        for column in table.columns:
            col_type = column.type
            pg_type_name = getattr(col_type, "name", None)
            enum_values = getattr(col_type, "enums", None)
            if not pg_type_name or not enum_values or pg_type_name in seen_types:
                continue
            seen_types.add(pg_type_name)
            live_labels = existing_enum_types.get(pg_type_name)
            if live_labels is None:
                continue  # brand-new enum type -- create_all() already created it in full
            for value in enum_values:
                if value in live_labels:
                    continue
                escaped = str(value).replace("'", "''")
                try:
                    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                        conn.execute(text(f"ALTER TYPE \"{pg_type_name}\" ADD VALUE IF NOT EXISTS '{escaped}'"))
                    print(f"[db] auto-migrated: added enum value {pg_type_name}.{value}")
                except Exception as e:
                    print(f"[db] WARNING: could not auto-add enum value {pg_type_name}.{value}: {e}")


def init_db() -> None:
    """Create all tables if they don't exist, then patch any tables that
    already exist but have drifted behind the current models (see
    _auto_add_missing_columns / _auto_add_missing_enum_values). Idempotent,
    safe to call on every startup."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _auto_add_missing_columns(engine)
    _auto_add_missing_enum_values(engine)


def get_session() -> Session:
    """FastAPI dependency: yields a SQLModel Session."""
    engine = get_engine()
    with Session(engine) as session:
        yield session


def shutdown_db() -> None:
    """Cleanly stop the embedded pgserver process, if we started one."""
    global _pgserver_instance
    if _pgserver_instance is not None:
        _pgserver_instance.cleanup()
        _pgserver_instance = None
