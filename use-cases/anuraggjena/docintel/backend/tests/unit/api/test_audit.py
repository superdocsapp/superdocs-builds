import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.api.v1.audit import get_audit_service


def make_entry(event_type="workflow.started"):
    e = MagicMock()
    e.id = str(uuid4())
    e.workspace_id = str(uuid4())
    e.event_type = event_type
    e.actor_id = None
    e.resource_type = "workflow_run"
    e.resource_id = str(uuid4())
    e.details = {}
    e.created_at = datetime.now(timezone.utc)
    return e


@pytest.mark.asyncio
async def test_get_workspace_audit_log():
    mock_service = AsyncMock()
    mock_service.get_workspace_audit_log = AsyncMock(return_value=[make_entry()])
    app.dependency_overrides[get_audit_service] = lambda: mock_service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/audit/workspace/{uuid4()}")
        assert response.status_code == 200
        assert len(response.json()) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_workspace_audit_log_with_filter():
    mock_service = AsyncMock()
    mock_service.get_workspace_audit_log = AsyncMock(return_value=[])
    app.dependency_overrides[get_audit_service] = lambda: mock_service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/audit/workspace/{uuid4()}?event_type=workflow.started")
        assert response.status_code == 200
        call_kwargs = mock_service.get_workspace_audit_log.call_args.kwargs
        assert call_kwargs.get("event_type") == "workflow.started"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_resource_audit_log():
    mock_service = AsyncMock()
    mock_service.get_resource_audit_log = AsyncMock(return_value=[make_entry()])
    app.dependency_overrides[get_audit_service] = lambda: mock_service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/audit/resource/workflow_run/{uuid4()}")
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
