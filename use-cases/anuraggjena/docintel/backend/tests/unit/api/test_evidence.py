"""
Unit tests for /evidence endpoints.

Regression coverage for 422 caused by path param name mismatch
(workflow_run_id in handler vs run_id expected by verify_run_workspace_access).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone
from httpx import AsyncClient, ASGITransport

from backend.main import app
from backend.api.v1.evidence import get_evidence_repo, get_citation_repo


def _make_evidence(run_id=None):
    e = MagicMock()
    e.id = str(uuid4())
    e.workflow_run_id = str(run_id or uuid4())
    e.document_id = str(uuid4())
    e.chunk_id = uuid4()
    e.extracted_text = "Relevant tariff text."
    e.evidence_type = "text"
    e.page_number = "1"
    e.relevance_score = 0.9
    e.created_at = datetime.now(timezone.utc)
    return e


def _make_citation(evidence_id=None):
    c = MagicMock()
    c.id = str(uuid4())
    c.claim_id = str(uuid4())
    c.evidence_id = str(evidence_id or uuid4())
    c.excerpt = "key excerpt"
    c.relevance_score = 0.85
    c.created_at = datetime.now(timezone.utc)
    return c


@pytest.mark.asyncio
async def test_list_evidence_for_run_not_422():
    """
    Regression: GET /evidence/run/{run_id} must NOT return 422.
    Previously failed because path param was workflow_run_id but dependency
    expected run_id — FastAPI treated run_id as a missing query param.
    """
    run_id = uuid4()
    mock_repo = AsyncMock()
    mock_repo.list_by_run = AsyncMock(return_value=[])
    app.dependency_overrides[get_evidence_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/evidence/run/{run_id}")
        assert response.status_code != 422, f"Got 422: {response.json()}"
        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_evidence_for_run_returns_items():
    """Evidence items for a run are returned correctly."""
    run_id = uuid4()
    ev = _make_evidence(run_id)
    mock_repo = AsyncMock()
    mock_repo.list_by_run = AsyncMock(return_value=[ev])
    app.dependency_overrides[get_evidence_repo] = lambda: mock_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/evidence/run/{run_id}")
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["evidence_type"] == "text"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_citations_for_run_not_422():
    """
    Regression: GET /evidence/run/{run_id}/citations must NOT return 422.
    """
    run_id = uuid4()
    ev = _make_evidence(run_id)
    citation = _make_citation(ev.id)

    mock_ev_repo = AsyncMock()
    mock_ev_repo.list_by_run = AsyncMock(return_value=[ev])
    mock_cit_repo = AsyncMock()
    mock_cit_repo.list_by_evidence = AsyncMock(return_value=[citation])

    app.dependency_overrides[get_evidence_repo] = lambda: mock_ev_repo
    app.dependency_overrides[get_citation_repo] = lambda: mock_cit_repo
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/evidence/run/{run_id}/citations")
        assert response.status_code != 422, f"Got 422: {response.json()}"
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 1
        assert items[0]["excerpt"] == "key excerpt"
    finally:
        app.dependency_overrides.clear()
