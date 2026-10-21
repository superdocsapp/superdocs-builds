import pytest
from uuid import uuid4
from backend.repositories.workspace import WorkspaceRepository
from backend.repositories.user import UserRepository

@pytest.mark.asyncio
async def test_create_workspace(db_session):
    """Test creating a new workspace"""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        email=f"test-{uuid4()}@example.com",
        password_hash="hashed_pw",
        name="Test User"
    )
    repo = WorkspaceRepository(db_session)

    workspace = await repo.create(
        name="Test Workspace",
        owner_id=user.id,
        workflow_type="tariff"
    )

    assert workspace.id is not None
    assert workspace.name == "Test Workspace"
    assert workspace.owner_user_id == user.id
    assert workspace.status == "active"

@pytest.mark.asyncio
async def test_get_workspace_by_id(db_session):
    """Test retrieving workspace by ID"""
    user_repo = UserRepository(db_session)
    user = await user_repo.create(
        email=f"test-{uuid4()}@example.com",
        password_hash="hashed_pw",
        name="Test User"
    )
    repo = WorkspaceRepository(db_session)

    created = await repo.create(name="Test", owner_id=user.id)
    retrieved = await repo.get_by_id(created.id)

    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.name == "Test"

@pytest.mark.asyncio
async def test_list_workspaces_by_owner(db_session):
    """Test listing workspaces for an owner"""
    user_repo = UserRepository(db_session)
    user1 = await user_repo.create(
        email=f"test-{uuid4()}@example.com",
        password_hash="hashed_pw",
        name="User 1"
    )
    user2 = await user_repo.create(
        email=f"test-{uuid4()}@example.com",
        password_hash="hashed_pw",
        name="User 2"
    )
    repo = WorkspaceRepository(db_session)

    await repo.create(name="WS1", owner_id=user1.id)
    await repo.create(name="WS2", owner_id=user1.id)
    await repo.create(name="WS3", owner_id=user2.id)

    workspaces = await repo.list_by_owner(user1.id)

    assert len(workspaces) == 2
    assert all(ws.owner_user_id == user1.id for ws in workspaces)
