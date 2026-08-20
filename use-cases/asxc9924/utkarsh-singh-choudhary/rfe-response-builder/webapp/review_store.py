"""
SQLite-backed store for in-progress ReviewSession objects.

The webapp used a plain in-memory dict for this originally, which only
works within a single process. On Render, a single service instance's
gunicorn workers are forked processes sharing the same local disk, so a
SQLite file at a fixed path is visible to every worker -- this removes
the "must run --workers 1" constraint that the in-memory version needed.

What this does NOT solve: horizontal scaling across multiple Render
*instances* (not just workers), since each instance has its own local
disk. That would need a real shared store (Postgres/Redis) instead of a
local SQLite file -- swapping that in only touches this module.

Sessions are pickled: they're built entirely server-side from our own
`ReviewSession`/`DraftItem` dataclasses (never deserialized from
user-controlled bytes), so this doesn't carry the usual "never unpickle
untrusted data" risk.
"""
from __future__ import annotations

import os
import pickle
import sqlite3
import time
from contextlib import closing

DEFAULT_DB_PATH = os.environ.get("REVIEW_STORE_PATH", "/tmp/rfe_review_sessions.sqlite3")
DEFAULT_TTL_S = int(os.environ.get("REVIEW_SESSION_TTL_S", "3600"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_sessions (
    review_id TEXT PRIMARY KEY,
    payload BLOB NOT NULL,
    created REAL NOT NULL
);
"""


class ReviewSessionStore:
    def __init__(self, db_path: str = DEFAULT_DB_PATH, ttl_s: int = DEFAULT_TTL_S):
        self.db_path = db_path
        self.ttl_s = ttl_s
        with closing(self._connect()) as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        # A short busy_timeout absorbs the rare cross-worker write
        # collision instead of raising "database is locked" -- review
        # traffic on this endpoint is low-volume by design (rate-limited
        # per IP), so lock contention should be rare in practice.
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def put(self, review_id: str, session) -> None:
        self._prune()
        payload = pickle.dumps(session)
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO review_sessions (review_id, payload, created) VALUES (?, ?, ?)",
                (review_id, payload, time.time()),
            )
            conn.commit()

    def get(self, review_id: str):
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload FROM review_sessions WHERE review_id = ?", (review_id,)
            ).fetchone()
        return pickle.loads(row[0]) if row else None

    def delete(self, review_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM review_sessions WHERE review_id = ?", (review_id,))
            conn.commit()

    def _prune(self) -> None:
        cutoff = time.time() - self.ttl_s
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM review_sessions WHERE created < ?", (cutoff,))
            conn.commit()
