"""Async engine + session factory, wired from settings.

A single engine per process; sessions are created per request/task. Tests point
DATABASE_URL at sqlite+aiosqlite and reuse this exact machinery.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _connect_args(database_url: str) -> dict:
    # SQLite needs a generous busy timeout so concurrent writers (our
    # idempotency race test) block-then-conflict instead of erroring instantly.
    if database_url.startswith("sqlite"):
        return {"timeout": 30}
    return {}


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            connect_args=_connect_args(settings.database_url),
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session and always closes it."""
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


def reset_engine_state() -> None:
    """Test hook: drop cached engine/sessionmaker so a new DATABASE_URL applies."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
