"""Pytest configuration and fixtures"""
import sys
from pathlib import Path

# Add parent directory to path so backend package can be imported
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
import pytest_asyncio
import asyncio
from pydantic_settings import SettingsConfigDict


@pytest.fixture
def test_env_vars(monkeypatch):
    """Fixture to set test environment variables"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://testuser:testpass@localhost:5432/testdb")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-minimum-32-characters-long")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")


@pytest.fixture
def clean_env(monkeypatch):
    """Fixture to clear environment variables"""
    # Remove all relevant env vars
    env_vars = [
        "DATABASE_URL",
        "SECRET_KEY",
        "GROQ_API_KEY",
        "STORAGE_PATH",
        "LOG_LEVEL",
        "ENVIRONMENT",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(scope="session")
def event_loop():
    """Session-scoped event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session():
    """Async database session fixture (requires actual DB setup)"""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from backend.config import settings

    # Convert sync URL to async URL if needed
    db_url = settings.database_url
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Create async engine
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(db_session):
    """Create a test user with 'user' role."""
    from backend.models.user import User
    from backend.repositories.user import UserRepository
    import uuid
    import bcrypt

    user_repo = UserRepository(db_session)

    # Check if user already exists
    from sqlalchemy import select
    result = await db_session.execute(
        select(User).where(User.email == "test_user@example.com")
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        return existing_user

    # Create new test user
    password_hash = bcrypt.hashpw(b"testpassword", bcrypt.gensalt(12)).decode('utf-8')

    user = User(
        id=uuid.uuid4(),
        email="test_user@example.com",
        password_hash=password_hash,
        name="Test User",
        role="user",
        is_active=True
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def test_reviewer(db_session):
    """Create a test user with 'reviewer' role."""
    from backend.models.user import User
    from backend.repositories.user import UserRepository
    import uuid
    import bcrypt

    # Check if user already exists
    from sqlalchemy import select
    result = await db_session.execute(
        select(User).where(User.email == "test_reviewer@example.com")
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        return existing_user

    # Create new test reviewer
    password_hash = bcrypt.hashpw(b"testpassword", bcrypt.gensalt(12)).decode('utf-8')

    user = User(
        id=uuid.uuid4(),
        email="test_reviewer@example.com",
        password_hash=password_hash,
        name="Test Reviewer",
        role="reviewer",
        is_active=True
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    return user


@pytest_asyncio.fixture
async def test_admin(db_session):
    """Create a test user with 'admin' role."""
    from backend.models.user import User
    import uuid
    import bcrypt

    # Check if user already exists
    from sqlalchemy import select
    result = await db_session.execute(
        select(User).where(User.email == "test_admin@example.com")
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        return existing_user

    # Create new test admin
    password_hash = bcrypt.hashpw(b"testpassword", bcrypt.gensalt(12)).decode('utf-8')

    user = User(
        id=uuid.uuid4(),
        email="test_admin@example.com",
        password_hash=password_hash,
        name="Test Admin",
        role="admin",
        is_active=True
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    return user


@pytest.fixture
def auth_token(test_user):
    """Generate JWT access token for test user."""
    from backend.core.auth.security import create_access_token
    from datetime import timedelta

    token = create_access_token(
        data={
            "sub": str(test_user.id),
            "email": test_user.email,
            "role": test_user.role
        },
        expires_delta=timedelta(minutes=30)
    )
    return token


@pytest.fixture
def reviewer_token(test_reviewer):
    """Generate JWT access token for test reviewer."""
    from backend.core.auth.security import create_access_token
    from datetime import timedelta

    token = create_access_token(
        data={
            "sub": str(test_reviewer.id),
            "email": test_reviewer.email,
            "role": test_reviewer.role
        },
        expires_delta=timedelta(minutes=30)
    )
    return token


@pytest.fixture
def admin_token(test_admin):
    """Generate JWT access token for test admin."""
    from backend.core.auth.security import create_access_token
    from datetime import timedelta

    token = create_access_token(
        data={
            "sub": str(test_admin.id),
            "email": test_admin.email,
            "role": test_admin.role
        },
        expires_delta=timedelta(minutes=30)
    )
    return token


@pytest.fixture
def auth_headers(auth_token):
    """Authorization headers with user token."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def reviewer_headers(reviewer_token):
    """Authorization headers with reviewer token."""
    return {"Authorization": f"Bearer {reviewer_token}"}


@pytest.fixture
def admin_headers(admin_token):
    """Authorization headers with admin token."""
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def mock_workspace_repo():
    """Mock workspace repository for service tests"""
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4
    from backend.repositories.workspace import WorkspaceRepository
    from backend.models.workspace import Workspace
    from datetime import datetime, timezone

    mock = AsyncMock(spec=WorkspaceRepository)

    # Create a proper Workspace mock object
    workspace_mock = MagicMock(spec=Workspace)
    workspace_mock.id = uuid4()
    workspace_mock.name = "Test Workspace"
    workspace_mock.owner_id = "user-123"
    workspace_mock.status = "active"
    workspace_mock.workflow_type = None
    workspace_mock.created_at = datetime.now(timezone.utc)
    workspace_mock.updated_at = datetime.now(timezone.utc)
    workspace_mock.deleted_at = None

    mock.create.return_value = workspace_mock
    return mock


@pytest_asyncio.fixture
async def test_user_2(db_session):
    """Create a second test user for cross-workspace testing."""
    from backend.models.user import User
    import uuid
    import bcrypt

    # Check if user already exists
    from sqlalchemy import select
    result = await db_session.execute(
        select(User).where(User.email == "test_user_2@example.com")
    )
    existing_user = result.scalar_one_or_none()

    if existing_user:
        return existing_user

    # Create new test user
    password_hash = bcrypt.hashpw(b"testpassword", bcrypt.gensalt(12)).decode('utf-8')

    user = User(
        id=uuid.uuid4(),
        email="test_user_2@example.com",
        password_hash=password_hash,
        name="Test User 2",
        role="user",
        is_active=True
    )

    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    return user


@pytest.fixture
def auth_token_user2(test_user_2):
    """Generate JWT access token for second test user."""
    from backend.core.auth.security import create_access_token
    from datetime import timedelta

    token = create_access_token(
        data={
            "sub": str(test_user_2.id),
            "email": test_user_2.email,
            "role": test_user_2.role
        },
        expires_delta=timedelta(minutes=30)
    )
    return token


@pytest.fixture
def auth_headers_user2(auth_token_user2):
    """Authorization headers for second test user."""
    return {"Authorization": f"Bearer {auth_token_user2}"}


@pytest_asyncio.fixture
async def test_workspace(db_session, test_user):
    """Create a test workspace owned by test_user."""
    from backend.models.workspace import Workspace
    from backend.repositories.workspace import WorkspaceRepository
    import uuid

    workspace_repo = WorkspaceRepository(db_session)

    workspace = await workspace_repo.create(
        name="Test Workspace",
        owner_user_id=test_user.id
    )
    await db_session.commit()
    await db_session.refresh(workspace)

    return workspace


@pytest_asyncio.fixture
async def client(db_session, test_user):
    """HTTP client with FastAPI app and test database."""
    from httpx import AsyncClient, ASGITransport
    from backend.main import app
    from backend.api.deps import get_db, get_current_user

    # Override get_db dependency to use test database
    async def override_get_db():
        yield db_session

    # Override get_current_user for tests that need it
    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    # Note: get_current_user override should be set per-test when needed

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    # Clean up overrides
    app.dependency_overrides.clear()


@pytest.fixture
def mock_get_current_user(test_user):
    """Factory to create get_current_user override for specific user."""
    def _override(user=None):
        async def override_get_current_user():
            return user if user is not None else test_user
        return override_get_current_user
    return _override
