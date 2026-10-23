"""Database bootstrap helpers (extensions + schema)."""

from sqlalchemy import text

from app.core.logging import get_logger
from app.database.base import Base
from app.database.session import engine

# Import models so metadata is populated
from app.models import Brief, Document, DocumentChunk, IngestSession  # noqa: F401

logger = get_logger(__name__)


async def init_database() -> None:
    """Ensure pgvector extension and application tables exist."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized (pgvector + tables)")


async def dispose_engine() -> None:
    await engine.dispose()
    logger.info("Database engine disposed")
