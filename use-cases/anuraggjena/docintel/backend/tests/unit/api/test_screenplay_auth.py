import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.api.deps import (
    get_current_user,
    verify_run_workspace_access,
    verify_formatting_item_workspace_access,
)
from backend.api.v1.screenplay import get_repo
from backend.models.workflow import WorkflowRun
from backend.models.screenplay import ScreenplayFormattingItem
from backend.models.user import User


def _make_user(role: str = "user") -> MagicMock:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = f"test-{u.id}@example.com"
    u.role = role
    u.is_active = True
    return u


def _make_item(item_id=None, run_id=None, status="pending") -> ScreenplayFormattingItem:
    now = datetime.now(timezone.utc)
    return ScreenplayFormattingItem(
        id=item_id or uuid.uuid4(),
        workflow_run_id=run_id or uuid.uuid4(),
        element_index=0,
        element_type="scene_heading",
        scene_number=1,
        character_name=None,
        original_text="INT. OFFICE - DAY",
        formatted_text="INT. OFFICE - DAY",
        change_type="none",
        reason=None,
        diff_tokens=[],
        content_drift=False,
        status=status,
        reviewer_comment=None,
        confidence_score=0.95,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_workspace_owner_user_role_can_approve_all():
    """Workspace owner with role='user' must receive 200 on approve-all."""
    run_id = uuid.uuid4()
    owner = _make_user(role="user")
    mock_run = MagicMock(spec=WorkflowRun)
    mock_run.id = run_id
    mock_run.workspace_id = uuid.uuid4()

    mock_repo = AsyncMock()
    mock_repo.approve_all_for_run = AsyncMock(return_value=5)

    async def mock_verify_run(run_id: uuid.UUID):
        return mock_run

    async def mock_get_user():
        return owner

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_run_workspace_access] = mock_verify_run
    app.dependency_overrides[get_repo] = lambda: mock_repo

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/screenplay/{run_id}/formatting-items/approve-all")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"
        data = response.json()
        assert data["approved_count"] == 5
        mock_repo.approve_all_for_run.assert_called_once_with(run_id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_workspace_owner_user_role_can_approve_single_item():
    """Workspace owner with role='user' must receive 200 on approve item."""
    run_id = uuid.uuid4()
    item_id = uuid.uuid4()
    owner = _make_user(role="user")
    item = _make_item(item_id=item_id, run_id=run_id, status="pending")
    approved_item = _make_item(item_id=item_id, run_id=run_id, status="approved")

    mock_repo = AsyncMock()
    mock_repo.approve = AsyncMock(return_value=approved_item)

    async def mock_verify_item(item_id: uuid.UUID):
        return item

    async def mock_get_user():
        return owner

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_formatting_item_workspace_access] = mock_verify_item
    app.dependency_overrides[get_repo] = lambda: mock_repo

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/screenplay/{run_id}/formatting-items/{item_id}/approve")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.json()}"
        data = response.json()
        assert data["status"] == "approved"
        mock_repo.approve.assert_called_once_with(item_id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_non_owner_receives_403_on_approve_all():
    """User without workspace access receives 403 on approve-all."""
    from fastapi import HTTPException

    run_id = uuid.uuid4()
    non_owner = _make_user(role="user")

    async def mock_verify_run_denied(run_id: uuid.UUID):
        raise HTTPException(status_code=403, detail="Access denied to this workspace")

    async def mock_get_user():
        return non_owner

    app.dependency_overrides[get_current_user] = mock_get_user
    app.dependency_overrides[verify_run_workspace_access] = mock_verify_run_denied

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/api/v1/screenplay/{run_id}/formatting-items/approve-all")

        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
    finally:
        app.dependency_overrides.clear()
