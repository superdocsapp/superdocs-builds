"""
Integration tests for Lineage API endpoints.

Tests verify all lineage and replay endpoints with proper error handling.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.main import app
from backend.api.v1.lineage import get_lineage_service, get_replay_service
from backend.core.lineage.models import (
    LineageGraph, LineageNode, LineageEdge,
    KnowledgeProvenance, ReplayTimeline, ReplayStage
)


@pytest.fixture
def mock_lineage_service():
    """Mock LineageService for testing"""
    service = MagicMock()
    service.get_claim_lineage = AsyncMock()
    service.get_knowledge_provenance = AsyncMock()
    service.get_regeneration_chain = AsyncMock()
    service.get_run_lineage = AsyncMock()
    return service


@pytest.fixture
def mock_replay_service():
    """Mock ReplayService for testing"""
    service = MagicMock()
    service.replay_run_execution = AsyncMock()
    service.replay_claim_execution = AsyncMock()
    return service


@pytest.fixture
def client(mock_lineage_service, mock_replay_service):
    """Test client for API calls with dependency overrides"""
    from backend.api.deps import get_current_user, verify_claim_workspace_access, verify_run_workspace_access
    from backend.models.user import User
    from backend.models.claim import Claim
    from backend.models.workflow import WorkflowRun
    from uuid import uuid4

    # Mock authentication - return a test admin user
    def mock_get_current_user():
        return User(
            id=uuid4(),
            email="test_admin@test.com",
            password_hash="fake_hash",
            name="Test Admin",
            role="admin",
            is_active=True
        )

    # Mock claim access verification - always allow for admin
    async def mock_verify_claim_access(claim_id, current_user=None, db=None):
        return Claim(
            id=claim_id,
            workflow_run_id=uuid4(),
            claim_type="test",
            content="test",
            status="pending"
        )

    # Mock run access verification - always allow for admin
    async def mock_verify_run_access(run_id, current_user=None, db=None):
        return WorkflowRun(
            id=run_id,
            workspace_id=uuid4(),
            workflow_id=uuid4(),
            status="completed",
            workflow_version="1.0",
            created_by="test"
        )

    app.dependency_overrides[get_lineage_service] = lambda: mock_lineage_service
    app.dependency_overrides[get_replay_service] = lambda: mock_replay_service
    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[verify_claim_workspace_access] = mock_verify_claim_access
    app.dependency_overrides[verify_run_workspace_access] = mock_verify_run_access
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test: GET /api/v1/lineage/claim/{claim_id}
# ---------------------------------------------------------------------------

def test_get_claim_lineage_returns_graph(client, mock_lineage_service):
    """Test getting claim lineage with default depth"""
    claim_id = uuid4()

    # Create mock graph
    graph = LineageGraph(
        nodes=[
            LineageNode(
                id=str(claim_id),
                type="claim",
                label="Test Claim",
                metadata={"status": "approved"}
            )
        ],
        edges=[],
        root_node_id=str(claim_id)
    )
    mock_lineage_service.get_claim_lineage.return_value = graph

    response = client.get(f"/api/v1/lineage/claim/{claim_id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["id"] == str(claim_id)
    assert data["root_node_id"] == str(claim_id)
    mock_lineage_service.get_claim_lineage.assert_awaited_once_with(claim_id, depth=3)


def test_get_claim_lineage_with_custom_depth(client, mock_lineage_service):
    """Test getting claim lineage with custom depth parameter"""
    claim_id = uuid4()

    graph = LineageGraph(
        nodes=[LineageNode(id=str(claim_id), type="claim", label="Test", metadata={})],
        edges=[],
        root_node_id=str(claim_id)
    )
    mock_lineage_service.get_claim_lineage.return_value = graph

    response = client.get(f"/api/v1/lineage/claim/{claim_id}?depth=5")

    assert response.status_code == 200
    mock_lineage_service.get_claim_lineage.assert_awaited_once_with(claim_id, depth=5)


def test_get_claim_lineage_depth_validation(client, mock_lineage_service):
    """Test depth parameter validation (min 1, max 5)"""
    claim_id = uuid4()

    # Test depth < 1
    response = client.get(f"/api/v1/lineage/claim/{claim_id}?depth=0")
    assert response.status_code == 422  # Validation error

    # Test depth > 5
    response = client.get(f"/api/v1/lineage/claim/{claim_id}?depth=10")
    assert response.status_code == 422  # Validation error


def test_get_claim_lineage_not_found(client, mock_lineage_service):
    """Test 404 when claim doesn't exist"""
    claim_id = uuid4()

    mock_lineage_service.get_claim_lineage.side_effect = ValueError(f"Claim {claim_id} not found")

    response = client.get(f"/api/v1/lineage/claim/{claim_id}")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test: GET /api/v1/lineage/run/{run_id}
# ---------------------------------------------------------------------------

# Removed: test_get_run_lineage_not_implemented
# This test is obsolete as get_run_lineage is now fully implemented


# ---------------------------------------------------------------------------
# Test: GET /api/v1/lineage/claim/{claim_id}/knowledge
# ---------------------------------------------------------------------------

def test_get_knowledge_provenance_returns_list(client, mock_lineage_service):
    """Test getting knowledge provenance for a claim"""
    claim_id = uuid4()
    knowledge_id = uuid4()
    source_run_id = uuid4()

    provenance = [
        KnowledgeProvenance(
            knowledge_entry_id=knowledge_id,
            source_run_id=source_run_id,
            content="Prior knowledge content",
            relevance_score=0.95,
            adoption_reason="Highly relevant",
            created_at=datetime.now(timezone.utc).isoformat()
        )
    ]
    mock_lineage_service.get_knowledge_provenance.return_value = provenance

    response = client.get(f"/api/v1/lineage/claim/{claim_id}/knowledge")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["knowledge_entry_id"] == str(knowledge_id)
    assert data[0]["relevance_score"] == 0.95
    mock_lineage_service.get_knowledge_provenance.assert_awaited_once_with(claim_id)


def test_get_knowledge_provenance_empty_list(client, mock_lineage_service):
    """Test getting knowledge provenance when none exists"""
    claim_id = uuid4()

    mock_lineage_service.get_knowledge_provenance.return_value = []

    response = client.get(f"/api/v1/lineage/claim/{claim_id}/knowledge")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# Test: GET /api/v1/lineage/claim/{claim_id}/regeneration-chain
# ---------------------------------------------------------------------------

def test_get_regeneration_chain_returns_claims(client, mock_lineage_service):
    """Test getting regeneration chain for a claim"""
    claim_id = uuid4()

    # Mock claim objects
    claim1 = MagicMock()
    claim1.id = uuid4()
    claim1.workflow_run_id = uuid4()
    claim1.content = "Original claim"
    claim1.status = "rejected"
    claim1.created_at = datetime.now(timezone.utc)
    claim1.updated_at = datetime.now(timezone.utc)
    claim1.review_id = None
    claim1.claim_type = "tariff"
    claim1.original_content = None
    claim1.edited_by = None
    claim1.source_stage = "analysis"
    claim1.confidence_score = None

    claim2 = MagicMock()
    claim2.id = claim_id
    claim2.workflow_run_id = uuid4()
    claim2.content = "Regenerated claim"
    claim2.status = "approved"
    claim2.created_at = datetime.now(timezone.utc)
    claim2.updated_at = datetime.now(timezone.utc)
    claim2.review_id = None
    claim2.claim_type = "tariff"
    claim2.original_content = None
    claim2.edited_by = None
    claim2.source_stage = "analysis"
    claim2.confidence_score = None

    mock_lineage_service.get_regeneration_chain.return_value = [claim1, claim2]

    response = client.get(f"/api/v1/lineage/claim/{claim_id}/regeneration-chain")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["id"] == str(claim1.id)
    assert data[1]["id"] == str(claim_id)
    mock_lineage_service.get_regeneration_chain.assert_awaited_once_with(claim_id)


# ---------------------------------------------------------------------------
# Test: GET /api/v1/replay/run/{run_id}
# ---------------------------------------------------------------------------

def test_replay_run_execution_returns_timeline(client, mock_replay_service):
    """Test replaying run execution"""
    run_id = uuid4()

    timeline = ReplayTimeline(
        run_id=run_id,
        stages=[
            ReplayStage(
                stage_name="document_ingestion",
                status="completed",
                started_at=datetime.now(timezone.utc).isoformat(),
                completed_at=datetime.now(timezone.utc).isoformat(),
                execution_time_ms=1500,
                inputs={"document_id": "123"},
                outputs={"chunks": 10},
                contributed_to_claim=False
            )
        ],
        knowledge_reused=[],
        review_decisions=[]
    )
    mock_replay_service.replay_run_execution.return_value = timeline

    response = client.get(f"/api/v1/replay/run/{run_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == str(run_id)
    assert len(data["stages"]) == 1
    assert data["stages"][0]["stage_name"] == "document_ingestion"
    mock_replay_service.replay_run_execution.assert_awaited_once_with(run_id)


def test_replay_run_execution_not_found(client, mock_replay_service):
    """Test 404 when run doesn't exist"""
    run_id = uuid4()

    mock_replay_service.replay_run_execution.side_effect = ValueError(f"WorkflowRun {run_id} not found")

    response = client.get(f"/api/v1/replay/run/{run_id}")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test: GET /api/v1/replay/claim/{claim_id}
# ---------------------------------------------------------------------------

# Removed: test_replay_claim_execution_not_implemented
# This test is obsolete as replay_claim_execution is now fully implemented


# ---------------------------------------------------------------------------
# Test: Edge cases and error handling
# ---------------------------------------------------------------------------

def test_invalid_uuid_format(client):
    """Test error handling for invalid UUID format"""
    response = client.get("/api/v1/lineage/claim/not-a-uuid")
    assert response.status_code == 422  # Validation error


def test_complex_lineage_graph(client, mock_lineage_service):
    """Test returning complex graph with multiple nodes and edges"""
    claim_id = uuid4()
    evidence_id = uuid4()
    document_id = uuid4()

    graph = LineageGraph(
        nodes=[
            LineageNode(id=str(claim_id), type="claim", label="Claim", metadata={}),
            LineageNode(id=str(evidence_id), type="evidence", label="Evidence", metadata={}),
            LineageNode(id=str(document_id), type="document", label="Doc.pdf", metadata={})
        ],
        edges=[
            LineageEdge(source_id=str(claim_id), target_id=str(evidence_id), edge_type="cited_by", metadata={}),
            LineageEdge(source_id=str(evidence_id), target_id=str(document_id), edge_type="extracted_from", metadata={})
        ],
        root_node_id=str(claim_id)
    )
    mock_lineage_service.get_claim_lineage.return_value = graph

    response = client.get(f"/api/v1/lineage/claim/{claim_id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 2


@pytest.mark.asyncio
async def test_get_run_lineage(client, mock_lineage_service):
    """Test GET /api/v1/lineage/run/:runId"""
    run_id = uuid4()

    # Mock graph with multiple claims
    mock_graph = LineageGraph(
        nodes=[
            LineageNode(id=str(uuid4()), type="claim", label="Claim 1", metadata={}),
            LineageNode(id=str(uuid4()), type="claim", label="Claim 2", metadata={}),
            LineageNode(id=str(uuid4()), type="document", label="Doc", metadata={})
        ],
        edges=[
            LineageEdge(source_id="1", target_id="3", edge_type="extracted_from", metadata={})
        ],
        root_node_id=None  # Multiple roots
    )

    mock_lineage_service.get_run_lineage.return_value = mock_graph

    response = client.get(f"/api/v1/lineage/run/{run_id}")

    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 1
    assert data["root_node_id"] is None
    mock_lineage_service.get_run_lineage.assert_called_once_with(run_id)


@pytest.mark.asyncio
async def test_replay_claim_execution(client, mock_replay_service):
    """Test GET /api/v1/replay/claim/:claimId"""
    claim_id = uuid4()
    run_id = uuid4()

    mock_timeline = ReplayTimeline(
        run_id=run_id,
        stages=[
            ReplayStage(
                stage_name="generate",
                status="completed",
                started_at="2026-01-01T00:00:00",
                completed_at="2026-01-01T00:01:00",
                execution_time_ms=60000,
                inputs={},
                outputs={"claim_ids": [str(claim_id)]},
                contributed_to_claim=True
            )
        ],
        knowledge_reused=[],
        review_decisions=[]
    )

    mock_replay_service.replay_claim_execution.return_value = mock_timeline

    response = client.get(f"/api/v1/replay/claim/{claim_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == str(run_id)
    assert len(data["stages"]) == 1
    assert data["stages"][0]["contributed_to_claim"] is True
    mock_replay_service.replay_claim_execution.assert_called_once_with(claim_id)
