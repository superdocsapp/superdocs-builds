import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, MagicMock

from backend.app.main import app
from backend.app.database import get_db

@pytest.fixture
def mock_db_session():
    """
    Unit testing fixture that creates a mock SQLAlchemy AsyncSession.
    """
    session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar.return_value = 1
    session.execute.return_value = mock_result
    return session

@pytest.fixture
def client(mock_db_session):
    """
    Unit testing fixture: returns TestClient overriding DB with a mock session.
    """
    async def override_get_db():
        yield mock_db_session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
