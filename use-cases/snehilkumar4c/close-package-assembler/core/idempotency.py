"""Client-side idempotency store, backed by Postgres.

ASSUMPTION (logged per the task doc's own standard — logged assumptions count in
our favor): llms-full.txt does not document SuperDocs's API deduplicating requests
by an Idempotency-Key header server-side. Rather than assume that behavior exists,
idempotency is enforced here, at OUR layer: before any money/token-costing call, we
check this store; after a successful call, we record the response. A retried request
with the same key is a provable no-op — it returns the cached response without
hitting the network again, regardless of whether SuperDocs itself dedupes anything.

This is deliberately the more defensive choice: correct whether or not the assumption
about their server holds.
"""

from __future__ import annotations

import json
from typing import Any

import psycopg

_SCHEMA = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    key TEXT PRIMARY KEY,
    response JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class IdempotencyStore:
    """A minimal, durable key -> response cache. One row per completed operation."""

    def __init__(self, conn_string: str) -> None:
        self._conn_string = conn_string

    def setup(self) -> None:
        """Idempotent itself: safe to call on every process start."""
        with psycopg.connect(self._conn_string) as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def get(self, key: str) -> dict[str, Any] | None:
        with psycopg.connect(self._conn_string) as conn:
            row = conn.execute(
                "SELECT response FROM idempotency_keys WHERE key = %s", (key,)
            ).fetchone()
            return row[0] if row else None

    def put(self, key: str, response: dict[str, Any]) -> None:
        """ON CONFLICT DO NOTHING: if two concurrent calls race on the same key,
        the first write wins and the second is silently a no-op — correct, since
        both calls represent the same logical operation."""
        with psycopg.connect(self._conn_string) as conn:
            conn.execute(
                "INSERT INTO idempotency_keys (key, response) VALUES (%s, %s) "
                "ON CONFLICT (key) DO NOTHING",
                (key, json.dumps(response)),
            )
            conn.commit()
