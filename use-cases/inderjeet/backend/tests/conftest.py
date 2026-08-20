import os
import pytest

# Override database URL setting to in-memory SQLite before any other imports occur
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.core.config import settings
settings.DATABASE_URL = "sqlite:///:memory:"

from app.db.session import Base, engine

@pytest.fixture(scope="session", autouse=True)
def init_db():
    """Initializes tables for session lifetime."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
