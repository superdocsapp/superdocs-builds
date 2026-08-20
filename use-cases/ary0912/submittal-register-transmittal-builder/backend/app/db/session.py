from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


def _create_db_engine():
    try:
        eng = create_engine(
            settings.database_url,
            pool_pre_ping=True,
        )
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return eng
    except Exception:
        return create_engine(
            "sqlite:///./submittal.db",
            connect_args={"check_same_thread": False},
        )


engine = _create_db_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()