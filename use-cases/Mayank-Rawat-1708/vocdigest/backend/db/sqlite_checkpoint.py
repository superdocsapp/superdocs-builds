"""
@file: backend/db/sqlite_checkpoint.py
@description: Optional SQLite checkpoint store, using aiosqlite as the stack specifies.
    Mirrors each stage checkpoint into a standalone file so run state survives losing the
    primary database entirely, and so a run can be inspected or recovered with nothing
    but the file and the sqlite3 CLI.
@flow: enabled by CHECKPOINT_SQLITE_PATH -> mirror_checkpoint() is called by the node
    base class after every successful primary write -> read_checkpoints() and
    recover_run() read it back for inspection or disaster recovery.
@dependencies:
    - aiosqlite: async SQLite driver
    - backend.config.settings: enable flag and file path

Design note: Postgres remains the authority. The task stack lists SQLite for checkpoint
persistence, but making it the sole store would put a run's status and its checkpoint in
two different databases with no shared transaction — a crash between the two writes
would leave them disagreeing, which is exactly the failure the checkpoint exists to
prevent. This mirror is therefore write-behind and best-effort: a mirror failure is
logged and never fails the run, because the authoritative write already succeeded.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from backend.config import settings

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id       TEXT NOT NULL,
    stage        TEXT NOT NULL,
    status       TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 1,
    error        TEXT,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS run_state (
    run_id       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    state_json   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_checkpoints_run ON checkpoints(run_id);
"""


def is_enabled() -> bool:
    return bool(settings.checkpoint_sqlite_path)


def _db_path() -> Path:
    path = Path(settings.checkpoint_sqlite_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@asynccontextmanager
async def _connect() -> AsyncIterator[aiosqlite.Connection]:
    """Open a mirror connection and always close it.

    An aiosqlite Connection is backed by a worker thread and cannot be re-entered, so
    this must be a context manager rather than a coroutine the caller then wraps in
    `async with` — doing that starts the thread twice and raises.
    """
    conn = await aiosqlite.connect(_db_path())
    try:
        # WAL lets a reader inspect the file while a run is writing to it, which is the
        # whole point of having a separate inspectable store.
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=10000")
        yield conn
    finally:
        await conn.close()


async def init_sqlite_checkpoints() -> None:
    """Create the mirror schema. Safe to call repeatedly."""
    if not is_enabled():
        return
    async with _connect() as conn:
        await conn.executescript(_SCHEMA)
        await conn.commit()
    logger.info("SQLite checkpoint mirror ready at %s", _db_path())


async def mirror_checkpoint(
    run_id: uuid.UUID,
    stage: str,
    status: str,
    result: dict[str, Any],
    *,
    attempts: int = 1,
    error: str | None = None,
) -> bool:
    """Write one stage checkpoint to the mirror. Returns False if it failed.

    Never raises. The authoritative write in Postgres has already committed by the time
    this is called, so a mirror failure must not take down a run that has genuinely made
    progress.
    """
    if not is_enabled():
        return False
    from backend.models import utcnow

    try:
        async with _connect() as conn:
            await conn.execute(
                """
                INSERT INTO checkpoints
                    (run_id, stage, status, result_json, attempts, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, stage) DO UPDATE SET
                    status=excluded.status,
                    result_json=excluded.result_json,
                    attempts=excluded.attempts,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    str(run_id), stage, status, json.dumps(result, default=str),
                    attempts, error, utcnow().isoformat(),
                ),
            )
            await conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - best-effort by design
        logger.warning("SQLite checkpoint mirror failed for %s/%s: %s", run_id, stage, exc)
        return False


async def mirror_run_state(
    run_id: uuid.UUID, status: str, state: dict[str, Any]
) -> bool:
    """Mirror the full graph state for a run."""
    if not is_enabled():
        return False
    from backend.models import utcnow

    try:
        async with _connect() as conn:
            await conn.execute(
                """
                INSERT INTO run_state (run_id, status, state_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at
                """,
                (str(run_id), status, json.dumps(state, default=str), utcnow().isoformat()),
            )
            await conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite run-state mirror failed for %s: %s", run_id, exc)
        return False


async def read_checkpoints(run_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """Read a run's mirrored checkpoints, keyed by stage."""
    if not is_enabled():
        return {}
    try:
        async with _connect() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT stage, status, result_json, attempts, error, updated_at "
                "FROM checkpoints WHERE run_id = ?",
                (str(run_id),),
            )
            rows = await cursor.fetchall()
        return {
            row["stage"]: {
                "stage": row["stage"],
                "status": row["status"],
                "result": json.loads(row["result_json"]),
                "attempts": row["attempts"],
                "error": row["error"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite checkpoint read failed for %s: %s", run_id, exc)
        return {}


async def recover_run(run_id: uuid.UUID) -> dict[str, Any] | None:
    """Reconstruct a run's state from the mirror alone.

    The recovery path for the case the mirror exists to cover: the primary database is
    gone, but the file is still on disk.
    """
    if not is_enabled():
        return None
    checkpoints = await read_checkpoints(run_id)
    if not checkpoints:
        return None
    try:
        async with _connect() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT status, state_json, updated_at FROM run_state WHERE run_id = ?",
                (str(run_id),),
            )
            row = await cursor.fetchone()
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite run-state read failed for %s: %s", run_id, exc)
        row = None

    completed = [s for s, c in checkpoints.items() if c["status"] in ("COMPLETE", "SKIPPED")]
    return {
        "run_id": str(run_id),
        "status": row["status"] if row else "UNKNOWN",
        "state": json.loads(row["state_json"]) if row else {},
        "checkpoints": checkpoints,
        "completed_stages": sorted(completed),
        "recovered_from": str(_db_path()),
    }


async def list_mirrored_runs() -> list[dict[str, Any]]:
    """Every run present in the mirror, most recently updated first."""
    if not is_enabled():
        return []
    try:
        async with _connect() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT run_id, status, updated_at FROM run_state ORDER BY updated_at DESC"
            )
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLite mirror listing failed: %s", exc)
        return []
