"""
Unit tests for BaselineContradictionCheck.

Tests contradiction detection logic for tariff claims.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock

from backend.core.quality_gate.baseline_check import BaselineContradictionCheck
from backend.core.quality_gate.checks import CheckStatus


class TestBaselineContradictionCheck:
    """Test BaselineContradictionCheck."""

    @pytest.fixture
    def mock_repos(self):
        """Create mock repositories."""
        claim_repo = Mock()
        chunk_repo = Mock()

        return {
            "claim_repo": claim_repo,
            "chunk_repo": chunk_repo
        }

    @pytest.fixture
    def check(self, mock_repos):
        """Create BaselineContradictionCheck with mock repositories."""
        return BaselineContradictionCheck(
            claim_repo=mock_repos["claim_repo"],
            chunk_repo=mock_repos["chunk_repo"]
        )

    @pytest.mark.asyncio
    async def test_no_baseline_skips(self, check):
        """Test check skips when no baseline_run_id."""
        state = {
            "workflow_run_id": str(uuid4()),
            "extracted_claims": []
        }

        result = await check.run(state, {})

        assert result.status == CheckStatus.SKIPPED
        assert "No baseline run ID" in result.message

    @pytest.mark.asyncio
    async def test_no_claims_skips(self, check):
        """Test check skips when no extracted claims."""
        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": []
        }

        result = await check.run(state, {})

        assert result.status == CheckStatus.SKIPPED
        assert "No new claims" in result.message

    @pytest.mark.asyncio
    async def test_no_contradictions_passes(self, check, mock_repos):
        """Test check passes when no contradictions found."""
        # Mock - no baseline claims (so no contradictions possible)
        mock_repos["claim_repo"].get_approved_claims_for_run = AsyncMock(return_value=[])

        from backend.modules.tariff.schemas import TariffClaim
        new_claim = TariffClaim(
            hs_code="8471.30",
            description="Laptop computer",
            duty_rate="5%"
        )

        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": [new_claim]
        }

        result = await check.run(state, {})

        assert result.status == CheckStatus.PASSED
        assert not result.blocking

    @pytest.mark.asyncio
    async def test_hs_code_contradiction_detected(self, check, mock_repos):
        """Test HS code contradiction is detected."""
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
            hs_code="8471.50",  # DIFFERENT HS code
            description="portable computer",  # SAME description
            duty_rate="5%"
        )

        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": [new_claim]
        }

        result = await check.run(state, {})

        assert result.status == CheckStatus.FAILED
        assert result.blocking is True
        assert "contradiction" in result.message.lower()
        assert result.details["total_contradictions"] == 1
        assert result.details["contradictions"][0]["field"] == "hs_code"
        assert result.details["contradictions"][0]["baseline_value"] == "8471.30"
        assert result.details["contradictions"][0]["new_value"] == "8471.50"

    @pytest.mark.asyncio
    async def test_duty_rate_contradiction_detected(self, check, mock_repos):
        """Test duty rate contradiction is detected."""
        baseline_claim = Mock(
            id=uuid4(),
            workflow_run_id=uuid4(),
            claim_type="duty_rate",
            content='{"duty_rate": "5%", "description": "electronic device"}',
            status="approved"
        )

        mock_repos["claim_repo"].get_approved_claims_for_run = AsyncMock(
            return_value=[baseline_claim]
        )

        from backend.modules.tariff.schemas import TariffClaim
        new_claim = TariffClaim(
            hs_code="8471.30",
            description="electronic device",  # SAME description
            duty_rate="10%"  # DIFFERENT duty rate
        )

        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": [new_claim]
        }

        result = await check.run(state, {})

        assert result.status == CheckStatus.FAILED
        assert result.blocking is True
        assert result.details["total_contradictions"] == 1
        assert result.details["contradictions"][0]["field"] == "duty_rate"
        assert result.details["contradictions"][0]["baseline_value"] == "5%"
        assert result.details["contradictions"][0]["new_value"] == "10%"

    @pytest.mark.asyncio
    async def test_similar_descriptions_required(self, check, mock_repos):
        """Test contradictions only detected when descriptions are similar."""
        baseline_claim = Mock(
            id=uuid4(),
            workflow_run_id=uuid4(),
            claim_type="hs_code",
            content='{"hs_code": "8471.30", "description": "portable computer laptop device"}',
            status="approved"
        )

        mock_repos["claim_repo"].get_approved_claims_for_run = AsyncMock(
            return_value=[baseline_claim]
        )

        from backend.modules.tariff.schemas import TariffClaim

        # Different HS code but DIFFERENT description - no contradiction
        different_product = TariffClaim(
            hs_code="8471.50",
            description="smartphone mobile phone",  # Completely different
            duty_rate="5%"
        )

        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": [different_product]
        }

        result = await check.run(state, {})

        # Should pass because descriptions are too different
        assert result.status == CheckStatus.PASSED

    @pytest.mark.asyncio
    async def test_multiple_contradictions(self, check, mock_repos):
        """Test multiple contradictions are detected."""
        baseline_claims = [
            Mock(
                id=uuid4(),
                workflow_run_id=uuid4(),
                claim_type="hs_code",
                content='{"hs_code": "8471.30", "description": "laptop computer"}',
                status="approved"
            ),
            Mock(
                id=uuid4(),
                workflow_run_id=uuid4(),
                claim_type="duty_rate",
                content='{"duty_rate": "5%", "description": "electronic tablet device"}',
                status="approved"
            )
        ]

        mock_repos["claim_repo"].get_approved_claims_for_run = AsyncMock(
            return_value=baseline_claims
        )

        from backend.modules.tariff.schemas import TariffClaim
        new_claims = [
            TariffClaim(
                hs_code="8471.50",  # Contradiction 1
                description="laptop computer",
                duty_rate="5%"
            ),
            TariffClaim(
                hs_code="8471.70",
                description="electronic tablet device",
                duty_rate="10%"  # Contradiction 2
            )
        ]

        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": new_claims
        }

        result = await check.run(state, {})

        assert result.status == CheckStatus.FAILED
        assert result.blocking is True
        assert result.details["total_contradictions"] == 2

    @pytest.mark.asyncio
    async def test_semantically_equivalent_not_contradiction(self, check, mock_repos):
        """Test semantically equivalent claims don't trigger contradiction."""
        baseline_claim = Mock(
            id=uuid4(),
            workflow_run_id=uuid4(),
            claim_type="hs_code",
            content='{"hs_code": "8471.30", "description": "portable laptop computer device"}',
            status="approved"
        )

        mock_repos["claim_repo"].get_approved_claims_for_run = AsyncMock(
            return_value=[baseline_claim]
        )

        from backend.modules.tariff.schemas import TariffClaim
        # Same HS code, slightly different wording
        new_claim = TariffClaim(
            hs_code="8471.30",  # SAME HS code
            description="laptop portable computer device",  # Same words, different order
            duty_rate="5%"
        )

        state = {
            "workflow_run_id": str(uuid4()),
            "baseline_run_id": str(uuid4()),
            "extracted_claims": [new_claim]
        }

        result = await check.run(state, {})

        # Should pass - no contradiction
        assert result.status == CheckStatus.PASSED

    def test_description_similarity_calculation(self, check):
        """Test description similarity calculation."""
        content1 = {"description": "portable laptop computer"}
        content2 = {"description": "laptop portable computer"}

        # High similarity - same words
        similarity = check._calculate_description_similarity(content1, content2)
        assert similarity > 0.8

        content3 = {"description": "smartphone mobile phone"}

        # Low similarity - different words
        similarity = check._calculate_description_similarity(content1, content3)
        assert similarity < 0.3

    def test_contradiction_detection_logic(self, check):
        """Test contradiction detection between claim contents."""
        # HS code contradiction
        new_content = {"hs_code": "8471.30", "description": "laptop computer"}
        baseline_content = {"hs_code": "8471.50", "description": "laptop computer"}

        contradiction = check._detect_contradiction(new_content, baseline_content)

        assert contradiction is not None
        assert contradiction["field"] == "hs_code"
        assert contradiction["baseline_value"] == "8471.50"
        assert contradiction["new_value"] == "8471.30"

        # No contradiction - same HS code
        baseline_content2 = {"hs_code": "8471.30", "description": "laptop computer"}

        contradiction = check._detect_contradiction(new_content, baseline_content2)

        assert contradiction is None
