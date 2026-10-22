from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=NullPool,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


AUDIT_EVENT_TYPE_ADDITIONS = [
    "packet_created",
    "packet_updated",
    "packet_deleted",
    "document_deleted",
    "processing_retried",
    "redaction_failed",
    "redaction_verified",
    "ai_analysis_failed",
]


async def init_db() -> None:
    import app.domain  # noqa: F401  — ensure all ORM models register with Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("postgresql"):
            for value in AUDIT_EVENT_TYPE_ADDITIONS:
                try:
                    await conn.execute(
                        text(
                            f"ALTER TYPE auditeventtype ADD VALUE"
                            f" IF NOT EXISTS '{value}'"
                        )
                    )
                except Exception:
                    pass  # type may not exist yet on fresh DB; create_all will handle it


async def close_db() -> None:
    await engine.dispose()
