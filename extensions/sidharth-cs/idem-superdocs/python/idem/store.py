"""The durable record of in-flight and completed operations.

SQLite because N4 requires the record to survive SIGKILL and R5 requires the
claim to be atomic, and stdlib sqlite3 gives both for free. An in-memory dict
plus a JSON file would need a write-ahead log and a lock to be as correct as
this already is.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

NEW = "new"
IN_FLIGHT = "in_flight"
SUCCEEDED = "succeeded"
FAILED = "failed"
UNKNOWN = "unknown"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    key         TEXT PRIMARY KEY,
    state       TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    job_id      TEXT,
    detail      TEXT,
    owner_pid   INTEGER,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Record:
    key: str
    state: str
    attempts: int
    result: object
    job_id: str | None
    detail: str | None
    owner_pid: int | None

    @property
    def owned_by_this_process(self) -> bool:
        return self.owner_pid == os.getpid()


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with self._connect() as conn:
            # WAL is a throughput choice, not the correctness mechanism — the
            # atomic claim comes from BEGIN IMMEDIATE and the primary key, both
            # of which hold under any journal mode. Switching to WAL needs an
            # exclusive lock and can report the database busy whatever the
            # timeout says, so many processes opening the same file at once will
            # sometimes lose this race. Failing the client over an optimisation
            # would be the wrong trade. Kept identical to the TypeScript store.
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            conn.executescript(_SCHEMA)

    # ponytail: a connection per call. sqlite handles the cross-process
    # locking, so this sidesteps every thread-affinity question for free.
    # Pool it if the operation rate ever makes the open cost visible.
    def _connect(self):
        """Wrapped in closing() deliberately.

        `with sqlite3.connect(...) as conn` is a *transaction* context manager:
        it commits or rolls back and leaves the connection open. Used that way
        with a connection per call, every store operation leaks a file
        descriptor — 335 of them over 200 operations, measured — until the
        process hits its limit and every subsequent open fails with
        "unable to open database file".

        The fuzzer found this by being the first thing to run enough operations
        to exhaust the limit. It is a real defect in the library, not in the
        test: any long-running caller would have died the same way.

        isolation_level=None means autocommit, so the transaction half of that
        context manager was doing nothing here anyway; claim() does its own
        explicit BEGIN IMMEDIATE / COMMIT.
        """
        conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return closing(conn)

    def get(self, key: str) -> Record | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM operations WHERE key = ?", (key,)).fetchone()
        return self._to_record(row) if row else None

    def state_of(self, key: str) -> str:
        rec = self.get(key)
        return rec.state if rec else NEW

    def claim(self, key: str) -> Record | None:
        """Atomically take ownership of a key. Returns None when the claim
        succeeded, or the existing record when someone else got there first.

        BEGIN IMMEDIATE takes the write lock before the read, so two callers
        racing on the same key cannot both see 'absent' and both insert (R5).
        """
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM operations WHERE key = ?", (key,)).fetchone()
                if row is not None:
                    conn.execute("COMMIT")
                    return self._to_record(row)
                conn.execute(
                    "INSERT INTO operations (key, state, attempts, owner_pid, created_at, updated_at)"
                    " VALUES (?, ?, 0, ?, ?, ?)",
                    (key, IN_FLIGHT, os.getpid(), now, now),
                )
                conn.execute("COMMIT")
                return None
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    def take_over(self, key: str) -> None:
        """Adopt a record this process now owns, after it was resolved out of
        an unknown or abandoned state."""
        self._update(key, state=IN_FLIGHT, owner_pid=os.getpid())

    def record_attempt(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE operations SET attempts = attempts + 1, updated_at = ? WHERE key = ?",
                (time.time(), key),
            )

    def bind_job(self, key: str, job_id: str) -> None:
        """Remember key -> job_id the moment a job id is first seen. This is
        the binding reconciliation depends on; recording it late is how a
        timeout ends up with nothing to ask the server about (SPEC.md 6)."""
        self._update(key, job_id=job_id)

    def succeed(self, key: str, result: object) -> None:
        self._update(key, state=SUCCEEDED, result_json=json.dumps(result), detail=None)

    def fail(self, key: str, detail: str) -> None:
        self._update(key, state=FAILED, detail=detail)

    def mark_unknown(self, key: str, detail: str) -> None:
        self._update(key, state=UNKNOWN, detail=detail)

    def release(self, key: str) -> None:
        """Drop the record entirely, returning the key to NEW.

        Only ever called after a retryable outcome, which the table guarantees
        means provably not applied (SPEC.md R10). Releasing a key that might
        have been applied would be the double-apply.
        """
        with self._connect() as conn:
            conn.execute("DELETE FROM operations WHERE key = ?", (key,))

    def _update(self, key: str, **fields: object) -> None:
        fields["updated_at"] = time.time()
        assigns = ", ".join(f"{name} = ?" for name in fields)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE operations SET {assigns} WHERE key = ?",
                (*fields.values(), key),
            )

    @staticmethod
    def _to_record(row: sqlite3.Row) -> Record:
        return Record(
            key=row["key"],
            state=row["state"],
            attempts=row["attempts"],
            result=json.loads(row["result_json"]) if row["result_json"] is not None else None,
            job_id=row["job_id"],
            detail=row["detail"],
            owner_pid=row["owner_pid"],
        )
