import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.api.v1.knowledge import get_knowledge_repo


def make_entry(workspace_id=None):
    e = MagicMock()
    e.id = str(uuid4())
    e.workspace_id = workspace_id or str(uuid4())
    e.workflow_type = "tariff"
    e.entry_type = "claim"
    e.content = "HS code 8471.30"
    e.confidence_score = 0.9
    e.tags = ["electronics"]
    e.source_run_id = None
    e.created_at = datetime.now(timezone.utc)
    return e


@pytest.mark.asyncio
async def test_list_workspace_knowledge_no_filter():
    entries = [make_entry(), make_entry()]
    mock_repo = AsyncMock()
    mock_repo.session = AsyncMock()
    # Mock the fallback query path
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = entries
    mock_repo.session.execute = AsyncMock(return_value=mock_result)

    app.dependency_overrides[get_knowledge_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/knowledge/workspace/{uuid4()}")
        assert response.status_code == 200
        assert len(response.json()) == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_workspace_knowledge_by_type():
    entries = [make_entry()]
    mock_repo = AsyncMock()
    mock_repo.list_by_workspace_and_type = AsyncMock(return_value=entries)

    app.dependency_overrides[get_knowledge_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/knowledge/workspace/{uuid4()}?workflow_type=tariff")
        assert response.status_code == 200
        assert mock_repo.list_by_workspace_and_type.called
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_workspace_knowledge_by_tags():
    entries = [make_entry()]
    mock_repo = AsyncMock()
    mock_repo.search_by_tags = AsyncMock(return_value=entries)

    app.dependency_overrides[get_knowledge_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/knowledge/workspace/{uuid4()}?tags=electronics,hardware")
        assert response.status_code == 200
        assert mock_repo.search_by_tags.called
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_create_knowledge_entry():
    entry = make_entry()
    mock_repo = AsyncMock()
    mock_repo.create = AsyncMock(return_value=entry)

    app.dependency_overrides[get_knowledge_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                f"/api/v1/knowledge/workspace/{uuid4()}",
                json={"workflow_type": "tariff", "entry_type": "claim", "content": "HS code 8471.30"}
            )
        assert response.status_code == 201
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_knowledge_entry_not_found():
    mock_repo = AsyncMock()
    mock_repo.get_by_id = AsyncMock(return_value=None)

    app.dependency_overrides[get_knowledge_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/v1/knowledge/workspace/{uuid4()}/entry/{uuid4()}")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()
