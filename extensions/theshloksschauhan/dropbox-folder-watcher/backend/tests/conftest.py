"""Shared pytest fixtures for database-backed tests.

Uses SQLite in-memory for speed — no PostgreSQL needed to run tests.
This is acceptable because our models use standard SQLAlchemy types.
The one PostgreSQL-specific type (UUID) is handled by mapping to String
in the test engine.
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from app.models.base import Base


@pytest.fixture(scope="function")
def db_session() -> Session:
    """Provide a clean in-memory SQLite database per test function.

    Tables are created fresh for each test, ensuring complete isolation.
    """
    # Use SQLite in-memory — fast, no external dependencies, no API key needed
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
    )

    # SQLite needs foreign key enforcement enabled explicitly
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables
    Base.metadata.create_all(engine)

    TestSession = sessionmaker(bind=engine)
    session = TestSession()

    yield session

    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()
