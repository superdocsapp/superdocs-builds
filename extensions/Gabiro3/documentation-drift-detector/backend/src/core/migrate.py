"""Apply schema migrations at service startup.

`001_init.sql` is mounted into `docker-entrypoint-initdb.d`, which Postgres
runs *only* when the data volume is first created. Any database that already
exists — which is every developer machine that has run this project once —
would never see a migration added later, and the service would start against a
schema missing the columns it writes to.

So migrations past the baseline are applied here instead, at startup, before
the app serves a request. Each file is recorded in `schema_migrations` so it
runs once; each file is also written to be independently idempotent, so a
crash between applying and recording is survivable.
"""

import logging
import re
from pathlib import Path

from sqlalchemy import text

from core.db import engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

# 001 creates the schema from nothing with bare CREATE TABLE statements; it is
# owned by initdb and is not safe to re-run. Everything after it is ours.
BASELINE = "001_init.sql"

_STATEMENT_SPLIT = re.compile(r";\s*(?:\n|$)")

# The services start together and would otherwise migrate concurrently, where
# even CREATE TABLE IF NOT EXISTS can collide on the system catalogue. An
# advisory lock makes the first one through do the work and the rest wait.
_LOCK_KEY = 4207654321


def _statements(sql: str) -> list[str]:
    """Split a migration into statements.

    asyncpg sends one statement per round trip, so a multi-statement script
    cannot be handed over as a single string. The migrations here are plain
    DDL with no function bodies or dollar-quoting, so splitting on semicolons
    at end of line is sufficient — and a stray split would surface loudly as a
    syntax error rather than silently corrupting anything.
    """
    stripped = re.sub(r"^\s*--[^\n]*$", "", sql, flags=re.MULTILINE)
    return [s.strip() for s in _STATEMENT_SPLIT.split(stripped) if s.strip()]


async def apply_migrations() -> list[str]:
    """Apply every unapplied migration after the baseline. Returns their names."""
    if not MIGRATIONS_DIR.is_dir():
        logger.warning("No migrations directory at %s", MIGRATIONS_DIR)
        return []

    pending = sorted(
        p for p in MIGRATIONS_DIR.glob("*.sql") if p.name != BASELINE
    )
    if not pending:
        return []

    applied: list[str] = []

    # One transaction for the whole run. Postgres DDL is transactional, so a
    # migration that fails partway leaves no half-applied schema behind, and a
    # transaction-scoped advisory lock is released on commit or rollback
    # without needing a finally block to guess whether it is still held.
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
            await conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    "  name TEXT PRIMARY KEY,"
                    "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()"
                    ")"
                )
            )

            done = {
                r[0]
                for r in (await conn.execute(text("SELECT name FROM schema_migrations"))).all()
            }

            for path in pending:
                if path.name in done:
                    continue
                logger.info("Applying migration %s", path.name)
                for statement in _statements(path.read_text(encoding="utf-8")):
                    await conn.execute(text(statement))
                await conn.execute(
                    text("INSERT INTO schema_migrations (name) VALUES (:n) "
                         "ON CONFLICT (name) DO NOTHING"),
                    {"n": path.name},
                )
                applied.append(path.name)
    except Exception:
        # A service running against a schema it cannot write to would fail
        # later and further from the cause. Fail here, loudly.
        logger.exception("Schema migration failed")
        raise

    if applied:
        logger.info("Applied migrations: %s", ", ".join(applied))
    return applied
