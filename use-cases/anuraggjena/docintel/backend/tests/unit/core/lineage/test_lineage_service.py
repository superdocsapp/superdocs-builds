import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from backend.core.lineage.service import LineageService
from backend.models.claim import Claim


@pytest.fixture
def mock_repositories():
    """Create mock repositories"""
    return {
        'lineage_link_repo': AsyncMock(),
        'claim_repo': AsyncMock(),
        'evidence_repo': AsyncMock(),
        'citation_repo': AsyncMock(),
        'knowledge_repo': AsyncMock(),
        'audit_repo': AsyncMock(),
        'stage_repo': AsyncMock(),
        'chunk_repo': AsyncMock(),
        'document_repo': AsyncMock(),
        'review_repo': AsyncMock(),
    }


@pytest.mark.asyncio
async def test_get_claim_lineage_basic(mock_repositories):
    """Test basic claim lineage construction"""
    service = LineageService(**mock_repositories)

    # Mock claim without review
    mock_claim = MagicMock(spec=Claim)
    mock_claim.id = uuid4()
    mock_claim.content = "Test claim"
    mock_claim.workflow_run_id = uuid4()
    mock_claim.status = "approved"
    mock_claim.source_stage = "generate"
    mock_claim.review_id = None  # No review associated

    mock_repositories['claim_repo'].get_by_id.return_value = mock_claim
    mock_repositories['citation_repo'].list_by_claim.return_value = []
    mock_repositories['lineage_link_repo'].get_links_by_source.return_value = []

    graph = await service.get_claim_lineage(mock_claim.id, depth=1)

    assert graph is not None
    assert len(graph.nodes) >= 1
    assert graph.root_node_id == str(mock_claim.id)


@pytest.mark.asyncio
async def test_get_knowledge_provenance(mock_repositories):
    """Test getting knowledge provenance for a claim"""
    service = LineageService(**mock_repositories)

    claim_id = uuid4()
    mock_link = MagicMock()
    mock_link.target_id = uuid4()
    mock_link.link_metadata = {"relevance_score": 0.95}

    mock_knowledge = MagicMock()
    mock_knowledge.id = mock_link.target_id
    mock_knowledge.content = "Prior knowledge content"
    mock_knowledge.source_run_id = uuid4()
    mock_knowledge.created_at = MagicMock()
    mock_knowledge.created_at.isoformat.return_value = "2026-01-01T00:00:00"

    mock_repositories['lineage_link_repo'].get_knowledge_links_for_claim.return_value = [mock_link]
    mock_repositories['knowledge_repo'].get_by_id.return_value = mock_knowledge

    provenance = await service.get_knowledge_provenance(claim_id)

    assert len(provenance) == 1
    assert provenance[0].content == "Prior knowledge content"
    assert provenance[0].relevance_score == 0.95


@pytest.mark.asyncio
async def test_get_claim_lineage_with_review(mock_repositories):
    """Test claim lineage construction with review relationship"""
    service = LineageService(**mock_repositories)

    review_id = uuid4()

    # Mock claim with review
    mock_claim = MagicMock(spec=Claim)
    mock_claim.id = uuid4()
    mock_claim.content = "Test claim with review"
    mock_claim.workflow_run_id = uuid4()
    mock_claim.status = "approved"
    mock_claim.source_stage = "generate"
    mock_claim.review_id = review_id  # Has associated review

    # Mock review
    mock_review = MagicMock()
    mock_review.id = review_id
    mock_review.status = "approved"
    mock_review.reviewer_id = "user-123"
    mock_review.notes = "Looks good"

    mock_repositories['claim_repo'].get_by_id.return_value = mock_claim
    mock_repositories['citation_repo'].list_by_claim.return_value = []
    mock_repositories['lineage_link_repo'].get_links_by_source.return_value = []
    mock_repositories['review_repo'].get_by_id.return_value = mock_review

    graph = await service.get_claim_lineage(mock_claim.id, depth=1)

    assert graph is not None
    assert len(graph.nodes) == 2  # Claim + Review
    assert graph.root_node_id == str(mock_claim.id)

    # Check that review node exists
    review_nodes = [n for n in graph.nodes if n.type == "review"]
    assert len(review_nodes) == 1
    assert review_nodes[0].metadata["status"] == "approved"

    # Check that review edge exists
    review_edges = [e for e in graph.edges if e.edge_type == "reviewed"]
    assert len(review_edges) == 1


@pytest.mark.asyncio
async def test_get_regeneration_chain(mock_repositories):
    """Test getting regeneration chain"""
    service = LineageService(**mock_repositories)

    claim_id = uuid4()
    original_claim_id = uuid4()

    mock_claim = MagicMock()
    mock_claim.id = claim_id
    mock_claim.content = "Regenerated claim"

    mock_link = MagicMock()
    mock_link.link_type = "regenerated_from"
    mock_link.target_id = original_claim_id

    mock_original_claim = MagicMock()
    mock_original_claim.id = original_claim_id
    mock_original_claim.content = "Original claim"

    async def mock_get_by_id(cid):
        if cid == claim_id:
            return mock_claim
        elif cid == original_claim_id:
            return mock_original_claim
        return None

    async def mock_get_links_by_source(entity_type, entity_id):
        if entity_id == claim_id:
            return [mock_link]
        return []

    mock_repositories['claim_repo'].get_by_id.side_effect = mock_get_by_id
    mock_repositories['lineage_link_repo'].get_links_by_source.side_effect = mock_get_links_by_source

    chain = await service.get_regeneration_chain(claim_id)

    assert len(chain) == 2
    assert chain[0].id == original_claim_id  # Original first
    assert chain[1].id == claim_id  # Regenerated second


@pytest.mark.asyncio
async def test_get_run_lineage(mock_repositories):
    """Test getting lineage for entire run"""
    service = LineageService(**mock_repositories)

    run_id = uuid4()
    claim1_id = uuid4()
    claim2_id = uuid4()

    # Mock two claims for the run
    mock_claim1 = MagicMock(spec=Claim)
    mock_claim1.id = claim1_id
    mock_claim1.content = "Claim 1"
    mock_claim1.workflow_run_id = run_id
    mock_claim1.status = "approved"
    mock_claim1.source_stage = "generate"
    mock_claim1.review_id = None

    mock_claim2 = MagicMock(spec=Claim)
    mock_claim2.id = claim2_id
    mock_claim2.content = "Claim 2"
    mock_claim2.workflow_run_id = run_id
    mock_claim2.status = "approved"
    mock_claim2.source_stage = "generate"
    mock_claim2.review_id = None

    mock_repositories['claim_repo'].list_by_run.return_value = [mock_claim1, mock_claim2]

    async def mock_get_by_id(cid):
        if cid == claim1_id:
            return mock_claim1
        elif cid == claim2_id:
            return mock_claim2
        return None

    mock_repositories['claim_repo'].get_by_id.side_effect = mock_get_by_id
    mock_repositories['citation_repo'].list_by_claim.return_value = []
    mock_repositories['lineage_link_repo'].get_links_by_source.return_value = []

    graph = await service.get_run_lineage(run_id)

    assert graph is not None
    assert len(graph.nodes) == 2  # Two claim nodes
    assert graph.root_node_id is None  # Multiple roots
    assert any(node.id == str(claim1_id) for node in graph.nodes)
    assert any(node.id == str(claim2_id) for node in graph.nodes)


@pytest.mark.asyncio
async def test_get_run_lineage_no_claims(mock_repositories):
    """Test getting lineage for run with no claims"""
    service = LineageService(**mock_repositories)

    run_id = uuid4()
    mock_repositories['claim_repo'].list_by_run.return_value = []

    graph = await service.get_run_lineage(run_id)

    assert graph is not None
    assert len(graph.nodes) == 0
    assert len(graph.edges) == 0
    assert graph.root_node_id is None
