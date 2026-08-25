import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.api.v1.quality_gate import get_config_repo, get_result_repo


def make_config(workspace_id=None):
    c = MagicMock()
    c.id = str(uuid4())
    c.workspace_id = workspace_id or str(uuid4())
    c.enabled = True
    c.block_on_failure = False
    c.checks_config = {}
    c.created_at = datetime.now(timezone.utc).isoformat()
    return c


def make_result(run_id=None):
    r = MagicMock()
    r.id = str(uuid4())
    r.workflow_run_id = run_id or str(uuid4())
    r.status = "passed"
    r.checks_run = 2
    r.checks_passed = 2
    r.checks_failed = 0
    r.blocking = False
    r.details = []
    r.created_at = datetime.now(timezone.utc).isoformat()
    return r


@pytest.mark.asyncio
async def test_get_config_not_found():
    mock_repo = AsyncMock()
    mock_repo.get_by_workspace = AsyncMock(return_value=None)
    app.dependency_overrides[get_config_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/quality-gate/workspace/{uuid4()}/config")
        assert response.status_code == 200
        assert response.json() is None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_config_found():
    workspace_id = uuid4()
    config = make_config(str(workspace_id))
    mock_repo = AsyncMock()
    mock_repo.get_by_workspace = AsyncMock(return_value=config)
    app.dependency_overrides[get_config_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/quality-gate/workspace/{workspace_id}/config")
        assert response.status_code == 200
        assert response.json()["enabled"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upsert_config_creates_new():
    mock_repo = AsyncMock()
    mock_repo.get_by_workspace = AsyncMock(return_value=None)
    mock_repo.create = AsyncMock(return_value=make_config())
    app.dependency_overrides[get_config_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/quality-gate/workspace/{uuid4()}/config",
                json={"enabled": True, "block_on_failure": False, "checks_config": {}}
            )
        assert response.status_code == 200
        assert mock_repo.create.called
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_upsert_config_updates_existing():
    existing = make_config()
    mock_repo = AsyncMock()
    mock_repo.get_by_workspace = AsyncMock(return_value=existing)
    mock_repo.update = AsyncMock(return_value=existing)
    app.dependency_overrides[get_config_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.put(
                f"/api/v1/quality-gate/workspace/{uuid4()}/config",
                json={"enabled": False, "block_on_failure": True, "checks_config": {}}
            )
        assert response.status_code == 200
        assert mock_repo.update.called
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_run_result():
    run_id = uuid4()
    result = make_result(str(run_id))
    mock_repo = AsyncMock()
    mock_repo.get_by_run = AsyncMock(return_value=result)
    app.dependency_overrides[get_result_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/quality-gate/run/{run_id}/result")
        assert response.status_code == 200
        assert response.json()["status"] == "passed"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_run_result_path_param_not_422():
    """
    Regression: GET /quality-gate/run/{run_id}/result must NOT return 422.
    Previously failed because path param was named workflow_run_id in the handler
    but the verify_run_workspace_access dependency expected run_id, causing FastAPI
    to demand run_id as a query parameter instead.
    """
    run_id = uuid4()
    mock_repo = AsyncMock()
    mock_repo.get_by_run = AsyncMock(return_value=None)  # no result yet is fine
    app.dependency_overrides[get_result_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/quality-gate/run/{run_id}/result")
        assert response.status_code != 422, f"Got 422: {response.json()}"
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()
