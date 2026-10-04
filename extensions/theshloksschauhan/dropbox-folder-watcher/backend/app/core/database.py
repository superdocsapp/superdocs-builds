"""Database engine, session factory, and base model."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator

from app.core.config import settings

engine_args = {}
if settings.database_url.startswith("postgresql"):
    engine_args = {
        "pool_size": 5,
        "max_overflow": 10,
    }
elif settings.database_url.startswith("sqlite"):
    engine_args = {
        "connect_args": {"check_same_thread": False}
    }

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    **engine_args
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that provides a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for use outside of FastAPI request lifecycle (workers)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
