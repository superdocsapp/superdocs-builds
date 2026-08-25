import asyncio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)

# Convert sync URL to async URL
async_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(async_url, echo=False)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def check_db_connection():
    """Check database connectivity with timeout"""
    try:
        async with asyncio.timeout(5.0):
            async with async_session_maker() as session:
                await session.execute(text("SELECT 1"))
        logger.info("database_connection_ok")
        return True
    except asyncio.TimeoutError:
        logger.error(
            "database_connection_failed",
            error="Connection timeout after 5 seconds",
            error_type="TimeoutError",
            exc_info=True
        )
        return False
    except SQLAlchemyError as e:
        logger.error(
            "database_connection_failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        return False
    except Exception as e:
        logger.error(
            "database_connection_failed",
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        return False
