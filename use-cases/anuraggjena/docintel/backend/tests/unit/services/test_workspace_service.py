import pytest
from uuid import uuid4
from unittest.mock import AsyncMock
from backend.services.workspace import WorkspaceService
from backend.models.workspace import Workspace

@pytest.mark.asyncio
async def test_create_workspace_service(mock_workspace_repo):
    """Test workspace creation via service"""
    service = WorkspaceService(mock_workspace_repo)
    user_id = uuid4()
    mock_workspace_repo.create.return_value = Workspace(
        id=uuid4(),
        name="Test Workspace",
        owner_user_id=user_id,
        workflow_type="tariff"
    )

    result = await service.create_workspace(
        name="Test Workspace",
        owner_user_id=user_id,
        workflow_type="tariff"
    )

    assert result.name == "Test Workspace"
    mock_workspace_repo.create.assert_called_once()

@pytest.mark.asyncio
async def test_get_workspace_service(mock_workspace_repo):
    """Test getting workspace via service"""
    service = WorkspaceService(mock_workspace_repo)
    workspace_id = uuid4()

    mock_workspace_repo.get_by_id.return_value = Workspace(
        id=workspace_id,
        name="Test",
        owner_user_id=uuid4()
    )

    result = await service.get_workspace(workspace_id)

    assert result is not None
    assert result.id == workspace_id
