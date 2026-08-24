import asyncio
import json
import sqlite3
from pathlib import Path

from review_fsm.models import Command, ReviewEvent, ReviewSnapshot, TransitionResult
from review_fsm.persistence import (
    ReviewPersistenceConflict,
    ReviewPersistenceError,
)


class SQLiteReviewPersistence:
    """Durable SQLite adapter with atomic snapshot/event/outbox commits."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS review_snapshots (
                    batch_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_events (
                    event_id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_commands (
                    idempotency_key TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    async def create(self, snapshot: ReviewSnapshot) -> None:
        async with self._lock:
            with self._connect() as connection:
                try:
                    connection.execute(
                        "INSERT INTO review_snapshots(batch_id,version,payload) VALUES (?,?,?)",
                        (snapshot.batch_id, snapshot.version, snapshot.model_dump_json()),
                    )
                except sqlite3.IntegrityError as exc:
                    raise ReviewPersistenceConflict("review batch already exists") from exc

    async def load(self, batch_id: str) -> ReviewSnapshot | None:
        async with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT payload FROM review_snapshots WHERE batch_id=?", (batch_id,)
                ).fetchone()
        return ReviewSnapshot.model_validate_json(str(row["payload"])) if row else None

    async def commit(
        self,
        event: ReviewEvent,
        result: TransitionResult,
        *,
        expected_version: int,
    ) -> bool:
        async with self._lock:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    duplicate = connection.execute(
                        "SELECT 1 FROM review_events WHERE event_id=?", (event.event_id,)
                    ).fetchone()
                    if duplicate:
                        connection.rollback()
                        return False
                    row = connection.execute(
                        "SELECT version FROM review_snapshots WHERE batch_id=?",
                        (event.batch_id,),
                    ).fetchone()
                    if row is None:
                        raise ReviewPersistenceError("review batch does not exist")
                    if int(row["version"]) != expected_version:
                        raise ReviewPersistenceConflict(
                            "review snapshot changed before commit"
                        )
                    connection.execute(
                        "INSERT INTO review_events(event_id,batch_id,payload) VALUES (?,?,?)",
                        (event.event_id, event.batch_id, event.model_dump_json()),
                    )
                    for command in result.commands:
                        connection.execute(
                            """INSERT OR IGNORE INTO review_commands
                            (idempotency_key,batch_id,payload) VALUES (?,?,?)""",
                            (
                                command.idempotency_key,
                                event.batch_id,
                                command.model_dump_json(),
                            ),
                        )
                    updated = connection.execute(
                        """UPDATE review_snapshots SET version=?,payload=?
                        WHERE batch_id=? AND version=?""",
                        (
                            result.snapshot.version,
                            result.snapshot.model_dump_json(),
                            event.batch_id,
                            expected_version,
                        ),
                    )
                    if updated.rowcount != 1:
                        raise ReviewPersistenceConflict(
                            "review snapshot changed before commit"
                        )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        return True

    async def commands(self, batch_id: str) -> tuple[Command, ...]:
        async with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """SELECT payload FROM review_commands WHERE batch_id=?
                    ORDER BY rowid""",
                    (batch_id,),
                ).fetchall()
        return tuple(Command.model_validate(json.loads(row["payload"])) for row in rows)
