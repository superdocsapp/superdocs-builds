"""
Store for in-progress ReviewSession objects, backed by SQLAlchemy.

History: this started as a plain in-memory dict (broken across gunicorn
worker processes), then moved to a local SQLite file (works across
workers on ONE Render instance, since forked workers share local disk,
but not across multiple instances -- each has its own disk). This
version adds a real shared-database backend (Postgres) as the
production path, selected automatically when a database URL is
configured, while keeping local SQLite as the zero-config default for
`python webapp/app.py` on a laptop.

Backend selection (first match wins):
  1. `REVIEW_STORE_URL` env var, if set -- any SQLAlchemy URL
     (e.g. `postgresql+psycopg2://user:pass@host/db`).
  2. `DATABASE_URL` env var, if set -- reused so a Render Postgres add-on
     wired up for the app doesn't need a second, separately-named env var
     (Render's `postgres://` scheme is normalized to
     `postgresql+psycopg2://` since SQLAlchemy 2.x / newer psycopg2
     dialects don't accept the bare `postgres://` scheme).
  3. Otherwise, local SQLite at `REVIEW_STORE_PATH` (default
     `/tmp/rfe_review_sessions.sqlite3`) -- unchanged local-dev behavior.

With a real Postgres URL configured, this solves the multi-*instance*
horizontal-scaling gap the SQLite version explicitly could not: every
Render instance/worker talks to the same database, so a review started
on one instance can be finalized after a request lands on a different
one. This is exercised in `tests/test_review_store.py` against SQLite
(this sandbox cannot reach a live Postgres server), but the code path is
identical SQLAlchemy Core regardless of dialect -- only the URL differs.

Sessions are pickled: they're built entirely server-side from our own
`ReviewSession`/`DraftItem` dataclasses (never deserialized from
user-controlled bytes), so this doesn't carry the usual "never unpickle
untrusted data" risk.
"""
from __future__ import annotations

import os
import pickle
import time

from sqlalchemy import (
    Column,
    Float,
    LargeBinary,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
)
from sqlalchemy.engine import Engine

DEFAULT_SQLITE_PATH = os.environ.get("REVIEW_STORE_PATH", "/tmp/rfe_review_sessions.sqlite3")
DEFAULT_TTL_S = int(os.environ.get("REVIEW_SESSION_TTL_S", "3600"))

_metadata = MetaData()

review_sessions = Table(
    "review_sessions",
    _metadata,
    Column("review_id", String(64), primary_key=True),
    Column("payload", LargeBinary, nullable=False),
    Column("created", Float, nullable=False),
)


def _normalize_url(url: str) -> str:
    """Render (and Heroku-style) Postgres URLs commonly use the bare
    `postgres://` scheme, which modern SQLAlchemy + psycopg2 combinations
    reject -- normalize to `postgresql+psycopg2://` so the same
    env-var value that already works for other tools works here too."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    return url


def _resolve_engine_url() -> str:
    url = os.environ.get("REVIEW_STORE_URL") or os.environ.get("DATABASE_URL")
    if url:
        return _normalize_url(url)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def _build_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        # Needed because Flask/gunicorn may use this connection from
        # different threads than the one that created it; SQLAlchemy's
        # own pooling still serializes actual access per-connection.
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        # A small pool is plenty for this workload (low-volume,
        # rate-limited review traffic) and pre_ping avoids handing out a
        # connection that a managed Postgres provider silently closed
        # after an idle period.
        engine = create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)
    return engine


class ReviewSessionStore:
    def __init__(self, url: str | None = None, ttl_s: int = DEFAULT_TTL_S):
        self.url = url or _resolve_engine_url()
        self.ttl_s = ttl_s
        self.engine = _build_engine(self.url)
        _metadata.create_all(self.engine, tables=[review_sessions])

    @property
    def backend(self) -> str:
        """'postgresql', 'sqlite', etc -- surfaced for /readyz and logs
        so it's obvious at a glance which backend a running instance is
        actually using."""
        return self.engine.dialect.name

    def put(self, review_id: str, session) -> None:
        self._prune()
        payload = pickle.dumps(session)
        with self.engine.begin() as conn:
            # Portable upsert without relying on dialect-specific
            # ON CONFLICT syntax: delete-then-insert inside one
            # transaction. review_id collisions are effectively
            # impossible (uuid4 hex) so this isn't a hot path needing a
            # single-statement upsert.
            conn.execute(delete(review_sessions).where(review_sessions.c.review_id == review_id))
            conn.execute(
                insert(review_sessions).values(review_id=review_id, payload=payload, created=time.time())
            )

    def get(self, review_id: str):
        with self.engine.connect() as conn:
            row = conn.execute(
                select(review_sessions.c.payload).where(review_sessions.c.review_id == review_id)
            ).fetchone()
        return pickle.loads(row[0]) if row else None

    def delete(self, review_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(review_sessions).where(review_sessions.c.review_id == review_id))

    def _prune(self) -> None:
        cutoff = time.time() - self.ttl_s
        with self.engine.begin() as conn:
            conn.execute(delete(review_sessions).where(review_sessions.c.created < cutoff))
