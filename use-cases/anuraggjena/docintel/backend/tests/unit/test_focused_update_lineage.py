"""
Unit tests for focused update lineage functionality.

Tests that focused updates create proper reused_from_baseline lineage links.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock

from backend.modules.tariff.stages.focused_update import FocusedUpdateStage
from backend.services.impact_analysis import ClaimImpact, ImpactAnalysisResult
from backend.models.claim import Claim
from backend.models.lineage import LineageLink


class MockClaimRepository:
    """Mock claim repository."""
    def __init__(self):
        self.claims = {}
        self.session = MockSession()

    async def get_by_id(self, claim_id):
        return self.claims.get(claim_id)


class MockLineageRepository:
    """Mock lineage repository."""
    def __init__(self):
        self.links = []

    async def create_link(self, **kwargs):
        if 'metadata' not in kwargs:
            kwargs['metadata'] = {}
        link = LineageLink(**kwargs)
        self.links.append(link)
        return link


class MockImpactService:
    """Mock impact analysis service."""
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


class TestFocusedUpdateLineage:
    """Test focused update lineage creation."""

    @pytest.mark.asyncio
    async def test_unchanged_claim_creates_reused_lineage(self):
        """Test that unchanged claims create reused_from_baseline lineage."""
        baseline_run_id = uuid4()
        new_run_id = uuid4()
        baseline_claim_id = uuid4()

        baseline_claim = Claim(
            id=baseline_claim_id,
            workflow_run_id=baseline_run_id,
            claim_type="hs_code",
            content='{"hs_code": "8471.30", "description": "Laptop"}',
            status="approved"
        )

        claim_repo = MockClaimRepository()
        claim_repo.claims[baseline_claim_id] = baseline_claim

        lineage_repo = MockLineageRepository()

        impact_result = ImpactAnalysisResult(
            baseline_run_id=baseline_run_id,
            new_document_id=uuid4(),
            unchanged_claims=[
                ClaimImpact(
                    claim_id=baseline_claim_id,
                    status="UNCHANGED",
                    reason="No changes",
                    confidence=1.0,
                    changed_chunk_ids=[],
                    baseline_claim_id=baseline_claim_id
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

        from backend.modules.tariff.schemas import TariffWorkflowState
        state = TariffWorkflowState(
            workflow_run_id=str(new_run_id),
            workspace_id=str(uuid4()),
            baseline_run_id=str(baseline_run_id),
            document_id=str(uuid4())
        )

        result = await stage.execute(state)

        # Verify lineage link was created
        assert len(lineage_repo.links) == 1
        link = lineage_repo.links[0]

        assert link.link_type == "reused_from_baseline"
        assert link.target_id == baseline_claim_id
        assert link.workflow_run_id == new_run_id
        assert link.stage_name == "focused_update"

        # Verify metadata
        assert link.metadata["reason"] == "unchanged_content"
        assert link.metadata["confidence"] == 1.0
        assert "content_hash" in link.metadata

    @pytest.mark.asyncio
    async def test_multiple_unchanged_claims_create_multiple_links(self):
        """Test that multiple unchanged claims create multiple lineage links."""
        baseline_run_id = uuid4()
        new_run_id = uuid4()

        claim1_id = uuid4()
        claim2_id = uuid4()

        claim1 = Claim(
            id=claim1_id,
            workflow_run_id=baseline_run_id,
            claim_type="hs_code",
            content='{"hs_code": "8471.30"}',
            status="approved"
        )

        claim2 = Claim(
            id=claim2_id,
            workflow_run_id=baseline_run_id,
            claim_type="duty_rate",
            content='{"duty_rate": "5%"}',
            status="approved"
        )

        claim_repo = MockClaimRepository()
        claim_repo.claims[claim1_id] = claim1
        claim_repo.claims[claim2_id] = claim2

        lineage_repo = MockLineageRepository()

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

        from backend.modules.tariff.schemas import TariffWorkflowState
        state = TariffWorkflowState(
            workflow_run_id=str(new_run_id),
            workspace_id=str(uuid4()),
            baseline_run_id=str(baseline_run_id),
            document_id=str(uuid4())
        )

        result = await stage.execute(state)

        # Verify two lineage links were created
        assert len(lineage_repo.links) == 2
        assert all(link.link_type == "reused_from_baseline" for link in lineage_repo.links)

    @pytest.mark.asyncio
    async def test_content_hash_preserved_in_lineage(self):
        """Test that content hash is preserved in lineage metadata."""
        baseline_run_id = uuid4()
        new_run_id = uuid4()
        baseline_claim_id = uuid4()

        original_content = '{"hs_code": "8471.30", "description": "Portable computer"}'

        baseline_claim = Claim(
            id=baseline_claim_id,
            workflow_run_id=baseline_run_id,
            claim_type="hs_code",
            content=original_content,
            status="approved"
        )

        claim_repo = MockClaimRepository()
        claim_repo.claims[baseline_claim_id] = baseline_claim

        lineage_repo = MockLineageRepository()

        impact_result = ImpactAnalysisResult(
            baseline_run_id=baseline_run_id,
            new_document_id=uuid4(),
            unchanged_claims=[
                ClaimImpact(
                    claim_id=baseline_claim_id,
                    status="UNCHANGED",
                    reason="No changes",
                    confidence=1.0,
                    changed_chunk_ids=[],
                    baseline_claim_id=baseline_claim_id
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

        from backend.modules.tariff.schemas import TariffWorkflowState
        state = TariffWorkflowState(
            workflow_run_id=str(new_run_id),
            workspace_id=str(uuid4()),
            baseline_run_id=str(baseline_run_id),
            document_id=str(uuid4())
        )

        result = await stage.execute(state)

        # Verify content hash is in metadata
        link = lineage_repo.links[0]
        assert "content_hash" in link.metadata

        # Compute expected hash
        expected_hash = stage._hash_content(original_content)
        assert link.metadata["content_hash"] == expected_hash

    @pytest.mark.asyncio
    async def test_affected_claims_marked_but_no_superseded_lineage_yet(self):
        """Test that affected claims are marked but superseded_by lineage waits for generation."""
        baseline_run_id = uuid4()
        new_run_id = uuid4()
        affected_claim_id = uuid4()

        affected_claim = Claim(
            id=affected_claim_id,
            workflow_run_id=baseline_run_id,
            claim_type="hs_code",
            content='{"hs_code": "8471.30"}',
            status="approved"
        )

        claim_repo = MockClaimRepository()
        claim_repo.claims[affected_claim_id] = affected_claim

        lineage_repo = MockLineageRepository()

        impact_result = ImpactAnalysisResult(
            baseline_run_id=baseline_run_id,
            new_document_id=uuid4(),
            unchanged_claims=[],
            affected_claims=[
                ClaimImpact(
                    claim_id=affected_claim_id,
                    status="AFFECTED",
                    reason="Referenced chunk changed",
                    confidence=0.9,
                    changed_chunk_ids=["chunk_5"],
                    baseline_claim_id=affected_claim_id
                )
            ],
            new_chunks=[],
            contradicted_claims=[],
            total_baseline_claims=1,
            unchanged_count=0,
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

        from backend.modules.tariff.schemas import TariffWorkflowState
        state = TariffWorkflowState(
            workflow_run_id=str(new_run_id),
            workspace_id=str(uuid4()),
            baseline_run_id=str(baseline_run_id),
            document_id=str(uuid4())
        )

        result = await stage.execute(state)

        # Affected claims don't create lineage yet (waits for generation stage)
        # Only unchanged claims create reused_from_baseline links
        assert len(lineage_repo.links) == 0

        # Verify affected_claims_count is reported
        assert result["affected_claims_count"] == 1
