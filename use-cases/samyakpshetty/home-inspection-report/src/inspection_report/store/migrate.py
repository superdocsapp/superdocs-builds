"""Schema migrations: ordered SQL files, applied once, recorded.

The schema used to be one `CREATE TABLE IF NOT EXISTS` block run on every start. That is
fine exactly once. The second release cannot add a column, because the table already exists
and the statement does nothing — so a deployment silently runs old columns against new code
and the failure shows up as a missing attribute somewhere far away.

This is deliberately not Alembic. Alembic earns its keep on autogeneration and downgrades,
and this build needs neither: what it needs is that a numbered file runs once, in order, and
that nobody can quietly change one that already ran. That is a page of code and a reviewer
can read all of it, which matters more here than the feature surface.

Three properties, and each is a thing that goes wrong in production:

* **Once, in order.** Applied names live in ``schema_migrations``; anything not there runs,
  sorted by filename.
* **An applied migration is immutable.** Each row keeps the file's sha256. If a file changes
  after it ran, startup fails loudly and names it, because the alternative is two databases
  that disagree about what "0002" means.
* **Concurrent starts are safe.** Two API processes booting together take a Postgres
  advisory lock, so one applies and the other waits and finds nothing to do.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import psycopg

from inspection_report.logging import get_logger

_log = get_logger("inspection_report.store.migrate")

# Any 64-bit constant; it only has to be the same in every process running this schema.
_LOCK_KEY = 8_233_907_115_442_001

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    name        TEXT PRIMARY KEY,
    sha256      TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


class MigrationError(RuntimeError):
    """The schema could not be brought up to date. The message names the file and the fix."""


def migrations_dir() -> Path:
    """Where the SQL lives. Overridable so tests can point at their own set."""
    import os

    return Path(os.environ.get("MIGRATIONS_DIR", "migrations"))


def _files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise MigrationError(
            f"no migrations directory at {directory}. It ships with the project; if you are "
            f"running outside Docker, set MIGRATIONS_DIR."
        )
    return sorted(directory.glob("*.sql"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply(conn: psycopg.Connection[dict[str, Any]], directory: Path | None = None) -> list[str]:
    """Bring the database up to date. Returns the names applied on this call."""
    directory = directory or migrations_dir()
    files = _files(directory)
    if not files:
        raise MigrationError(f"{directory} contains no .sql files")

    with conn.cursor() as cur:
        cur.execute(_LEDGER)
        conn.commit()
        # Serialise concurrent starts. Released when the transaction ends.
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))

        cur.execute("SELECT name, sha256 FROM schema_migrations")
        applied = {row["name"]: row["sha256"] for row in cur.fetchall()}

        # Refuse before changing anything: a mismatch means two deployments disagree about
        # what a migration contains, and applying more on top would bury it.
        for path in files:
            recorded = applied.get(path.name)
            if recorded is not None and recorded != _sha(path):
                raise MigrationError(
                    f"{path.name} has changed since it was applied to this database. A "
                    f"migration that has run is immutable — restore the original contents "
                    f"and add a new file for the change you want."
                )

        ran: list[str] = []
        for path in files:
            if path.name in applied:
                continue
            _log.info("migration_applying", extra={"migration": path.name})
            cur.execute(path.read_text())
            cur.execute(
                "INSERT INTO schema_migrations (name, sha256) VALUES (%s, %s)",
                (path.name, _sha(path)),
            )
            ran.append(path.name)
    conn.commit()

    if ran:
        _log.info("migrations_applied", extra={"count": len(ran), "names": ",".join(ran)})
    return ran


def pending(conn: psycopg.Connection[dict[str, Any]], directory: Path | None = None) -> list[str]:
    """What would run. Useful for a deploy check that does not want to apply anything."""
    directory = directory or migrations_dir()
    with conn.cursor() as cur:
        cur.execute(_LEDGER)
        conn.commit()
        cur.execute("SELECT name FROM schema_migrations")
        applied = {row["name"] for row in cur.fetchall()}
    return [p.name for p in _files(directory) if p.name not in applied]
