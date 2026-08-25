import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock
from uuid import uuid4
from datetime import datetime, timezone

from backend.main import app
from backend.models.workspace import Workspace
from backend.api.deps import get_workspace_service


@pytest.mark.asyncio
async def test_create_workspace():
    """Test POST /api/v1/workspaces"""
    # Create mock service
    mock_service = AsyncMock()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
        owner_id="user-123",
        status="active",
        workflow_type=None,
        created_at=now,
        updated_at=now,
        deleted_at=None
    )
    mock_service.create_workspace.return_value = mock_workspace

    # Override dependency
    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/workspaces",
                json={"name": "Test Workspace", "owner_id": "user-123"}
            )

            assert response.status_code == 201
            data = response.json()
            assert data["name"] == "Test Workspace"
            assert data["owner_id"] == "user-123"
            assert data["status"] == "active"
            assert "id" in data
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_workspace_with_workflow_type():
    """Test POST /api/v1/workspaces with workflow_type"""
    mock_service = AsyncMock()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_workspace = Workspace(
        id=workspace_id,
        name="Research Workspace",
        owner_id="user-123",
        status="active",
        workflow_type="research",
        created_at=now,
        updated_at=now,
        deleted_at=None
    )
    mock_service.create_workspace.return_value = mock_workspace

    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/workspaces",
                json={
                    "name": "Research Workspace",
                    "owner_id": "user-123",
                    "workflow_type": "research"
                }
            )

            assert response.status_code == 201
            data = response.json()
            assert data["workflow_type"] == "research"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_workspaces():
    """Test GET /api/v1/workspaces"""
    mock_service = AsyncMock()
    now = datetime.now(timezone.utc)

    mock_service.list_user_workspaces.return_value = [
        Workspace(
            id=uuid4(),
            name="WS1",
            owner_id="user-123",
            status="active",
            workflow_type=None,
            created_at=now,
            updated_at=now,
            deleted_at=None
        ),
        Workspace(
            id=uuid4(),
            name="WS2",
            owner_id="user-123",
            status="active",
            workflow_type="research",
            created_at=now,
            updated_at=now,
            deleted_at=None
        )
    ]

    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/workspaces?owner_id=user-123")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
            assert data[0]["name"] == "WS1"
            assert data[1]["name"] == "WS2"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_workspace():
    """Test GET /api/v1/workspaces/{workspace_id}"""
    mock_service = AsyncMock()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)

    mock_workspace = Workspace(
        id=workspace_id,
        name="Test Workspace",
        owner_id="user-123",
        status="active",
        workflow_type=None,
        created_at=now,
        updated_at=now,
        deleted_at=None
    )
    mock_service.get_workspace.return_value = mock_workspace

    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/workspaces/{workspace_id}")

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Test Workspace"
            assert data["id"] == str(workspace_id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_workspace_not_found():
    """Test GET /api/v1/workspaces/{workspace_id} with non-existent ID"""
    mock_service = AsyncMock()
    workspace_id = uuid4()

    mock_service.get_workspace.return_value = None

    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/api/v1/workspaces/{workspace_id}")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_workspace():
    """Test PATCH /api/v1/workspaces/{workspace_id}"""
    mock_service = AsyncMock()
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)

    updated_workspace = Workspace(
        id=workspace_id,
        name="Updated Workspace",
        owner_id="user-123",
        status="active",
        workflow_type="analysis",
        created_at=now,
        updated_at=now,
        deleted_at=None
    )
    mock_service.update_workspace.return_value = updated_workspace

    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/workspaces/{workspace_id}",
                json={"name": "Updated Workspace", "workflow_type": "analysis"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Updated Workspace"
            assert data["workflow_type"] == "analysis"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_update_workspace_not_found():
    """Test PATCH /api/v1/workspaces/{workspace_id} with non-existent ID"""
    mock_service = AsyncMock()
    workspace_id = uuid4()

    mock_service.update_workspace.return_value = None

    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.patch(
                f"/api/v1/workspaces/{workspace_id}",
                json={"name": "Updated"}
            )

            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_workspace():
    """Test DELETE /api/v1/workspaces/{workspace_id}"""
    mock_service = AsyncMock()
    workspace_id = uuid4()

    mock_service.delete_workspace.return_value = True

    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/v1/workspaces/{workspace_id}")

            assert response.status_code == 204
            assert response.content == b''
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_workspace_not_found():
    """Test DELETE /api/v1/workspaces/{workspace_id} with non-existent ID"""
    mock_service = AsyncMock()
    workspace_id = uuid4()

    mock_service.delete_workspace.return_value = False

    app.dependency_overrides[get_workspace_service] = lambda: mock_service

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/v1/workspaces/{workspace_id}")

            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
