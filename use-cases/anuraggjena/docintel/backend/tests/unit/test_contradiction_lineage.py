"""
Unit tests for contradiction lineage functionality.

Tests that baseline contradictions create proper lineage links.
"""

import pytest
from uuid import uuid4, UUID
from unittest.mock import AsyncMock, Mock

from backend.core.quality_gate.baseline_check import BaselineContradictionCheck


class TestContradictionLineage:
    """Test contradiction lineage creation."""

    @pytest.fixture
    def mock_repos(self):
        """Create mock repositories."""
        claim_repo = Mock()
        chunk_repo = Mock()
        lineage_repo = Mock()

        lineage_repo.create_link = AsyncMock()

        return {
            "claim_repo": claim_repo,
            "chunk_repo": chunk_repo,
            "lineage_repo": lineage_repo
        }

    @pytest.fixture
    def check_with_lineage(self, mock_repos):
        """Create BaselineContradictionCheck with lineage repo."""
        return BaselineContradictionCheck(
            claim_repo=mock_repos["claim_repo"],
            chunk_repo=mock_repos["chunk_repo"],
            lineage_repo=mock_repos["lineage_repo"]
        )

    @pytest.mark.asyncio
    async def test_contradiction_creates_lineage(self, check_with_lineage, mock_repos):
        """Test that contradictions create lineage links."""
        baseline_run_id = uuid4()
        workflow_run_id = uuid4()
        baseline_claim_id = uuid4()
        new_claim_id = uuid4()

        contradictions = [
            {
                "baseline_claim_id": str(baseline_claim_id),
                "new_claim_id": str(new_claim_id),
                "field": "hs_code",
                "baseline_value": "8471.30",
                "new_value": "8471.50",
                "description_similarity": 0.95
            }
        ]

        await check_with_lineage._create_contradiction_lineage(
            contradictions=contradictions,
            baseline_run_id=baseline_run_id,
            workflow_run_id=workflow_run_id
        )

        # Verify lineage link was created
        assert mock_repos["lineage_repo"].create_link.called
        call_kwargs = mock_repos["lineage_repo"].create_link.call_args.kwargs

        # Verify link type and IDs
        assert call_kwargs["link_type"] == "contradicts"
        assert call_kwargs["source_type"] == "claim"
        assert call_kwargs["source_id"] == UUID(str(new_claim_id))
        assert call_kwargs["target_type"] == "claim"
        assert call_kwargs["target_id"] == UUID(str(baseline_claim_id))
        assert call_kwargs["workflow_run_id"] == workflow_run_id
        assert call_kwargs["stage_name"] == "quality_gate"

        # Verify metadata
        metadata = call_kwargs["metadata"]
        assert metadata["baseline_run_id"] == str(baseline_run_id)
        assert metadata["field"] == "hs_code"
        assert metadata["baseline_value"] == "8471.30"
        assert metadata["new_value"] == "8471.50"
        assert metadata["similarity"] == 0.95
        assert metadata["contradiction_detected"] is True

    @pytest.mark.asyncio
    async def test_multiple_contradictions_create_multiple_links(self, check_with_lineage, mock_repos):
        """Test that multiple contradictions create multiple lineage links."""
        baseline_run_id = uuid4()
        workflow_run_id = uuid4()

        contradictions = [
            {
                "baseline_claim_id": str(uuid4()),
                "new_claim_id": str(uuid4()),
                "field": "hs_code",
                "baseline_value": "8471.30",
                "new_value": "8471.50",
                "description_similarity": 0.9
            },
            {
                "baseline_claim_id": str(uuid4()),
                "new_claim_id": str(uuid4()),
                "field": "duty_rate",
                "baseline_value": "5%",
                "new_value": "10%",
                "description_similarity": 0.85
            }
        ]

        await check_with_lineage._create_contradiction_lineage(
            contradictions=contradictions,
            baseline_run_id=baseline_run_id,
            workflow_run_id=workflow_run_id
        )

        # Verify two lineage links were created
        assert mock_repos["lineage_repo"].create_link.call_count == 2

    @pytest.mark.asyncio
    async def test_contradiction_lineage_skipped_when_no_repo(self, mock_repos):
        """Test that lineage creation is skipped when no repository."""
        check = BaselineContradictionCheck(
            claim_repo=mock_repos["claim_repo"],
            chunk_repo=mock_repos["chunk_repo"],
            lineage_repo=None  # No lineage repo
        )

        contradictions = [
            {
                "baseline_claim_id": str(uuid4()),
                "new_claim_id": str(uuid4()),
                "field": "hs_code",
                "baseline_value": "8471.30",
                "new_value": "8471.50"
            }
        ]

        # Should not raise exception
        await check._create_contradiction_lineage(
            contradictions=contradictions,
            baseline_run_id=uuid4(),
            workflow_run_id=uuid4()
        )

    @pytest.mark.asyncio
    async def test_contradiction_lineage_handles_unknown_claim(self, check_with_lineage, mock_repos):
        """Test that lineage handles unknown new_claim_id."""
        contradictions = [
            {
                "baseline_claim_id": str(uuid4()),
                "new_claim_id": "unknown",  # Unknown claim
                "field": "hs_code",
                "baseline_value": "8471.30",
                "new_value": "8471.50"
            }
        ]

        await check_with_lineage._create_contradiction_lineage(
            contradictions=contradictions,
            baseline_run_id=uuid4(),
            workflow_run_id=uuid4()
        )

        # Should not create lineage for unknown claims
        assert not mock_repos["lineage_repo"].create_link.called

    @pytest.mark.asyncio
    async def test_contradiction_detected_but_lineage_waits_for_claim_id(self, check_with_lineage, mock_repos):
        """
        Test that contradictions are detected but lineage waits for claim IDs.

        Note: extracted_claims are Pydantic models without IDs at quality gate stage.
        Lineage links are created later when claims are persisted with IDs.
        """
        baseline_claim = Mock(
            id=uuid4(),
            workflow_run_id=uuid4(),
            claim_type="hs_code",
            content='{"hs_code": "8471.30", "description": "portable computer"}',
            status="approved"
        )

        mock_repos["claim_repo"].get_approved_claims_for_run = AsyncMock(
            return_value=[baseline_claim]
        )

        from backend.modules.tariff.schemas import TariffClaim
        new_claim = TariffClaim(
            hs_code="8471.50",  # Different HS code
            description="portable computer",  # Same description
            duty_rate="5%"
        )

        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": [new_claim]
        }

        result = await check_with_lineage.run(state, {})

        # Verify contradiction was detected
        assert result.status.value == "failed"
        assert result.details["total_contradictions"] == 1

        # Lineage NOT created yet because new_claim doesn't have ID yet
        # (IDs are assigned when claims are persisted in generate stage)
        assert not mock_repos["lineage_repo"].create_link.called

    @pytest.mark.asyncio
    async def test_no_lineage_when_no_contradictions(self, check_with_lineage, mock_repos):
        """Test that no lineage is created when no contradictions."""
        mock_repos["claim_repo"].get_approved_claims_for_run = AsyncMock(
            return_value=[]
        )

        from backend.modules.tariff.schemas import TariffClaim
        new_claim = TariffClaim(
            hs_code="8471.50",
            description="portable computer",
            duty_rate="5%"
        )

        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": [new_claim]
        }

        result = await check_with_lineage.run(state, {})

        # No contradictions
        assert result.status.value == "passed"

        # No lineage created
        assert not mock_repos["lineage_repo"].create_link.called
