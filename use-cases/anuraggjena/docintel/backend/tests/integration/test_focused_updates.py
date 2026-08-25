"""
Integration tests for focused update workflows.

Tests that focused updates actually preserve unchanged claims and regenerate only affected ones.
"""

import pytest
import asyncio
from uuid import uuid4
from datetime import datetime, timezone

from backend.modules.tariff.stages.focused_update import FocusedUpdateStage
from backend.services.impact_analysis import ImpactAnalysisService, ClaimImpact, ImpactAnalysisResult
from backend.models.claim import Claim
from backend.models.lineage import LineageLink


class MockClaimRepository:
    """Mock claim repository for testing."""
    def __init__(self):
        self.claims = {}
        self.session = MockSession()

    async def get_by_id(self, claim_id):
        return self.claims.get(claim_id)

    async def get_approved_claims_for_run(self, run_id):
        return [c for c in self.claims.values() if c.workflow_run_id == run_id and c.status == "approved"]


class MockLineageRepository:
    """Mock lineage repository for testing."""
    def __init__(self):
        self.links = []

    async def create_link(self, **kwargs):
        # Ensure metadata is initialized
        if 'metadata' not in kwargs:
            kwargs['metadata'] = {}
        link = LineageLink(**kwargs)
        self.links.append(link)
        return link


class MockImpactService:
    """Mock impact analysis service for testing."""
    def __init__(self, result=None):
        self.result = result

    async def analyze_update_impact(self, new_document_id, baseline_run_id):
        return self.result


class MockSession:
    """Mock database session."""
    def __init__(self):
        self.added_objects = []

    def add(self, obj):
        self.added_objects.append(obj)

    async def flush(self):
        pass

    async def refresh(self, obj):
        obj.id = uuid4()

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_focused_update_no_baseline():
    """Test focused update skips when no baseline_run_id."""
    claim_repo = MockClaimRepository()
    lineage_repo = MockLineageRepository()
    impact_service = MockImpactService()

    stage = FocusedUpdateStage(
        impact_service=impact_service,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo
    )

    # State without baseline_run_id
    from backend.modules.tariff.schemas import TariffWorkflowState
    state = TariffWorkflowState(
        workflow_run_id=str(uuid4()),
        workspace_id=str(uuid4()),
        document_id=str(uuid4())
    )

    result = await stage.execute(state)

    assert result.get("skip") is True
    assert result.get("focused_update_completed") is False


@pytest.mark.asyncio
async def test_focused_update_all_unchanged():
    """Test focused update with all claims unchanged."""
    baseline_run_id = uuid4()
    new_run_id = uuid4()

    # Create baseline claims
    claim1_id = uuid4()
    claim2_id = uuid4()

    claim1 = Claim(
        id=claim1_id,
        workflow_run_id=baseline_run_id,
        claim_type="hs_code",
        content='{"hs_code": "8471.30", "description": "Laptop"}',
        status="approved"
    )
    claim2 = Claim(
        id=claim2_id,
        workflow_run_id=baseline_run_id,
        claim_type="duty_rate",
        content='{"duty_rate": "5%", "description": "Laptop"}',
        status="approved"
    )

    claim_repo = MockClaimRepository()
    claim_repo.claims[claim1_id] = claim1
    claim_repo.claims[claim2_id] = claim2

    lineage_repo = MockLineageRepository()

    # Create impact result: all unchanged
    impact_result = ImpactAnalysisResult(
        baseline_run_id=baseline_run_id,
        new_document_id=uuid4(),
        unchanged_claims=[
            ClaimImpact(
                claim_id=claim1_id,
                status="UNCHANGED",
                reason="No changes",
                confidence=1.0,
                changed_chunk_ids=[],
                baseline_claim_id=claim1_id
            ),
            ClaimImpact(
                claim_id=claim2_id,
                status="UNCHANGED",
                reason="No changes",
                confidence=1.0,
                changed_chunk_ids=[],
                baseline_claim_id=claim2_id
            )
        ],
        affected_claims=[],
        new_chunks=[],
        contradicted_claims=[],
        total_baseline_claims=2,
        unchanged_count=2,
        affected_count=0,
        new_count=0,
        contradicted_count=0
    )

    impact_service = MockImpactService(result=impact_result)

    stage = FocusedUpdateStage(
        impact_service=impact_service,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo
    )

    # Execute focused update
    from backend.modules.tariff.schemas import TariffWorkflowState
    state = TariffWorkflowState(
        workflow_run_id=str(new_run_id),
        workspace_id=str(uuid4()),
        baseline_run_id=str(baseline_run_id),
        document_id=str(uuid4())
    )

    result = await stage.execute(state)

    # Verify results
    assert result["focused_update_completed"] is True
    assert result["unchanged_claims_count"] == 2
    assert result["affected_claims_count"] == 0
    assert result["new_chunks_count"] == 0
    assert len(result["preserved_claim_ids"]) == 2

    # Verify lineage links created
    assert len(lineage_repo.links) == 2
    assert all(link.link_type == "reused_from_baseline" for link in lineage_repo.links)


@pytest.mark.asyncio
async def test_focused_update_one_affected():
    """Test focused update with one affected claim."""
    baseline_run_id = uuid4()
    new_run_id = uuid4()

    # Create baseline claims
    claim1_id = uuid4()
    claim2_id = uuid4()

    claim1 = Claim(
        id=claim1_id,
        workflow_run_id=baseline_run_id,
        claim_type="hs_code",
        content='{"hs_code": "8471.30", "description": "Laptop"}',
        status="approved"
    )
    claim2 = Claim(
        id=claim2_id,
        workflow_run_id=baseline_run_id,
        claim_type="duty_rate",
        content='{"duty_rate": "5%", "description": "Laptop"}',
        status="approved"
    )

    claim_repo = MockClaimRepository()
    claim_repo.claims[claim1_id] = claim1
    claim_repo.claims[claim2_id] = claim2

    lineage_repo = MockLineageRepository()

    # Create impact result: claim1 unchanged, claim2 affected
    impact_result = ImpactAnalysisResult(
        baseline_run_id=baseline_run_id,
        new_document_id=uuid4(),
        unchanged_claims=[
            ClaimImpact(
                claim_id=claim1_id,
                status="UNCHANGED",
                reason="No changes",
                confidence=1.0,
                changed_chunk_ids=[],
                baseline_claim_id=claim1_id
            )
        ],
        affected_claims=[
            ClaimImpact(
                claim_id=claim2_id,
                status="AFFECTED",
                reason="Referenced chunk changed",
                confidence=0.9,
                changed_chunk_ids=["chunk_5"],
                baseline_claim_id=claim2_id
            )
        ],
        new_chunks=[],
        contradicted_claims=[],
        total_baseline_claims=2,
        unchanged_count=1,
        affected_count=1,
        new_count=0,
        contradicted_count=0
    )

    impact_service = MockImpactService(result=impact_result)

    stage = FocusedUpdateStage(
        impact_service=impact_service,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo
    )

    # Execute focused update
    from backend.modules.tariff.schemas import TariffWorkflowState
    state = TariffWorkflowState(
        workflow_run_id=str(new_run_id),
        workspace_id=str(uuid4()),
        baseline_run_id=str(baseline_run_id),
        document_id=str(uuid4())
    )

    result = await stage.execute(state)

    # Verify results
    assert result["focused_update_completed"] is True
    assert result["unchanged_claims_count"] == 1
    assert result["affected_claims_count"] == 1
    assert result["new_chunks_count"] == 0
    assert len(result["preserved_claim_ids"]) == 1  # Only claim1 preserved

    # Verify lineage: only 1 link for unchanged claim
    assert len(lineage_repo.links) == 1
    assert lineage_repo.links[0].link_type == "reused_from_baseline"


@pytest.mark.asyncio
async def test_focused_update_new_chunks():
    """Test focused update with new chunks detected."""
    baseline_run_id = uuid4()
    new_run_id = uuid4()

    claim_repo = MockClaimRepository()
    lineage_repo = MockLineageRepository()

    # Create impact result: new chunks added
    impact_result = ImpactAnalysisResult(
        baseline_run_id=baseline_run_id,
        new_document_id=uuid4(),
        unchanged_claims=[],
        affected_claims=[],
        new_chunks=["new_chunk_1", "new_chunk_2"],
        contradicted_claims=[],
        total_baseline_claims=0,
        unchanged_count=0,
        affected_count=0,
        new_count=2,
        contradicted_count=0
    )

    impact_service = MockImpactService(result=impact_result)

    stage = FocusedUpdateStage(
        impact_service=impact_service,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo
    )

    # Execute focused update
    from backend.modules.tariff.schemas import TariffWorkflowState
    state = TariffWorkflowState(
        workflow_run_id=str(new_run_id),
        workspace_id=str(uuid4()),
        baseline_run_id=str(baseline_run_id),
        document_id=str(uuid4())
    )

    result = await stage.execute(state)

    # Verify results
    assert result["focused_update_completed"] is True
    assert result["new_chunks_count"] == 2
    assert len(result["affected_chunk_ids"]) == 2
    assert "new_chunk_1" in result["affected_chunk_ids"]
    assert "new_chunk_2" in result["affected_chunk_ids"]


@pytest.mark.asyncio
async def test_focused_update_contradiction():
    """Test focused update with contradicted claims."""
    baseline_run_id = uuid4()
    new_run_id = uuid4()
    claim_id = uuid4()

    claim_repo = MockClaimRepository()
    lineage_repo = MockLineageRepository()

    # Create impact result: contradiction detected
    impact_result = ImpactAnalysisResult(
        baseline_run_id=baseline_run_id,
        new_document_id=uuid4(),
        unchanged_claims=[],
        affected_claims=[],
        new_chunks=[],
        contradicted_claims=[
            ClaimImpact(
                claim_id=claim_id,
                status="CONTRADICTED",
                reason="HS code conflict",
                confidence=0.95,
                changed_chunk_ids=["chunk_3"],
                baseline_claim_id=claim_id
            )
        ],
        total_baseline_claims=1,
        unchanged_count=0,
        affected_count=0,
        new_count=0,
        contradicted_count=1
    )

    impact_service = MockImpactService(result=impact_result)

    stage = FocusedUpdateStage(
        impact_service=impact_service,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo
    )

    # Execute focused update
    from backend.modules.tariff.schemas import TariffWorkflowState
    state = TariffWorkflowState(
        workflow_run_id=str(new_run_id),
        workspace_id=str(uuid4()),
        baseline_run_id=str(baseline_run_id),
        document_id=str(uuid4())
    )

    result = await stage.execute(state)

    # Verify results
    assert result["focused_update_completed"] is True
    assert result["contradicted_claims_count"] == 1
    assert len(result["contradictions"]) == 1
    assert result["contradictions"][0]["reason"] == "HS code conflict"


@pytest.mark.asyncio
async def test_focused_update_content_hash_preservation():
    """Test that unchanged content preserves exact hash."""
    baseline_run_id = uuid4()
    new_run_id = uuid4()
    claim_id = uuid4()

    original_content = '{"hs_code": "8471.30", "description": "Portable computer"}'

    baseline_claim = Claim(
        id=claim_id,
        workflow_run_id=baseline_run_id,
        claim_type="hs_code",
        content=original_content,
        status="approved"
    )

    claim_repo = MockClaimRepository()
    claim_repo.claims[claim_id] = baseline_claim

    lineage_repo = MockLineageRepository()

    # Create impact result: unchanged
    impact_result = ImpactAnalysisResult(
        baseline_run_id=baseline_run_id,
        new_document_id=uuid4(),
        unchanged_claims=[
            ClaimImpact(
                claim_id=claim_id,
                status="UNCHANGED",
                reason="No changes",
                confidence=1.0,
                changed_chunk_ids=[],
                baseline_claim_id=claim_id
            )
        ],
        affected_claims=[],
        new_chunks=[],
        contradicted_claims=[],
        total_baseline_claims=1,
        unchanged_count=1,
        affected_count=0,
        new_count=0,
        contradicted_count=0
    )

    impact_service = MockImpactService(result=impact_result)

    stage = FocusedUpdateStage(
        impact_service=impact_service,
        claim_repository=claim_repo,
        lineage_repository=lineage_repo
    )

    # Execute focused update
    from backend.modules.tariff.schemas import TariffWorkflowState
    state = TariffWorkflowState(
        workflow_run_id=str(new_run_id),
        workspace_id=str(uuid4()),
        baseline_run_id=str(baseline_run_id),
        document_id=str(uuid4())
    )

    result = await stage.execute(state)

    # Verify content preserved exactly
    new_claim = claim_repo.session.added_objects[0]
    assert new_claim.content == original_content

    # Verify hash stored in lineage metadata
    lineage_link = lineage_repo.links[0]
    # Access metadata (named differently in model vs param)
    metadata = lineage_link.metadata if hasattr(lineage_link, 'metadata') else lineage_link.link_metadata
    assert metadata is not None
    assert "content_hash" in metadata

    # Compute expected hash
    expected_hash = stage._hash_content(original_content)
    assert metadata["content_hash"] == expected_hash
