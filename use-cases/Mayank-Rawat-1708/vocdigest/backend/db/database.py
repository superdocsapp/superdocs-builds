"""
@file: backend/db/database.py
@description: Async SQLAlchemy engine and session plumbing. Provides one engine per
    process, a session factory, a transactional context manager used by every node, and
    a FastAPI dependency. Also owns first-boot schema setup for the pgvector extension.
@flow: get_engine() lazily builds the AsyncEngine -> session_scope() yields an
    AsyncSession wrapped in a transaction that commits on clean exit and rolls back on
    any exception -> nodes and routes use it so no write escapes a transaction.
@dependencies:
    - sqlalchemy.ext.asyncio: AsyncEngine / AsyncSession
    - backend.config.settings: database URL and echo flag
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import settings
from backend.models import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.db_echo,
            pool_pre_ping=True,  # a killed run leaves stale conns; ping before reuse
            pool_size=10,
            max_overflow=20,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # objects stay usable after commit
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session. Commits on success, rolls back on any exception.

    Every DB write in the system goes through this, which satisfies the "every write is
    wrapped in a transaction" requirement without each caller remembering to do it.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session."""
    async with session_scope() as session:
        yield session


async def init_db(create_all: bool = False) -> None:
    """Ensure the pgvector extension exists, optionally creating tables.

    Alembic owns the schema in normal operation; create_all=True is for tests and the
    demo path where running a migration chain would be friction for no benefit.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        # pgvector only exists on Postgres. Running this unconditionally made the app
        # log a hard error on SQLite even though the models are dialect-portable.
        if engine.dialect.name == "postgresql":
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        if create_all:
            await conn.run_sync(Base.metadata.create_all)
    logger.info(
        "Database ready (dialect=%s, create_all=%s)", engine.dialect.name, create_all
    )


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
