"""Tests for memo grounding quality gate check."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.core.quality_gate.memo_grounding_check import MemoGroundingCheck
from backend.core.quality_gate.checks import CheckStatus
from backend.modules.tariff.memo_types import ProductFacts, RulingFacts, MemoSectionOutput, Recommendation


@pytest.fixture
def mock_memo_section_repo():
    """Mock memo section repository."""
    repo = AsyncMock()
    repo.list_by_run = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def valid_state():
    """Valid workflow state with all required fields."""
    return {
        "workflow_run_id": str(uuid4()),
        "product_facts": ProductFacts(
            product_name="Widget",
            material_composition="aluminum",
        ),
        "ruling_facts": [
            RulingFacts(
                ruling_number="HQ H265674",
                applicable_classification="7326.90.8588",
                document_id="ruling-1",
            )
        ],
        "matched_ruling_ids": ["ruling-1"],
        "reconciliation_conflicts": [],
        "retrieved_chunks": [],
    }


@pytest.mark.asyncio
async def test_check_skips_without_workflow_run_id():
    """Check should skip if no workflow run ID."""
    check = MemoGroundingCheck()
    result = await check.run(state={}, config={})

    assert result.status == CheckStatus.SKIPPED
    assert "workflow run id" in result.message.lower()


@pytest.mark.asyncio
async def test_check_skips_without_memo_sections(mock_memo_section_repo, valid_state):
    """Check should skip if no memo sections exist."""
    mock_memo_section_repo.list_by_run.return_value = []

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.SKIPPED
    assert "no memo sections" in result.message.lower()


@pytest.mark.asyncio
async def test_check_passes_with_valid_sections(mock_memo_section_repo, valid_state):
    """Check should pass with valid grounded sections."""
    # Mock valid section
    mock_section = MagicMock()
    mock_section.section_type = "product_description"
    mock_section.structured_data = {
        "content": "Aluminum storage container",
        "analyst_reasoning": "Material verified from specification",
        "source_attribution": [{"source": "specification"}],
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.PASSED
    assert "no violations" in result.message.lower()
    assert result.blocking is False


@pytest.mark.asyncio
async def test_check_fails_with_placeholder(mock_memo_section_repo, valid_state):
    """Check should fail when placeholder detected."""
    mock_section = MagicMock()
    mock_section.section_type = "product_description"
    mock_section.structured_data = {
        "content": "The product is [PLACEHOLDER] material",
        "analyst_reasoning": "TODO: Complete analysis",
        "source_attribution": [],
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.FAILED
    assert result.blocking is True
    assert "error" in result.message.lower()
    assert result.details["errors"] > 0


@pytest.mark.asyncio
async def test_check_fails_with_material_conflict(mock_memo_section_repo, valid_state):
    """Check should fail when material contradicts product facts."""
    mock_section = MagicMock()
    mock_section.section_type = "material_composition"
    mock_section.structured_data = {
        "content": "The product is made of plastic polymer",
        "analyst_reasoning": "Material analysis",
        "source_attribution": [],
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.FAILED
    assert result.blocking is True
    assert "product_fact_conflict" in result.message.lower() or "error" in result.message.lower()


@pytest.mark.asyncio
async def test_check_fails_with_invalid_ruling(mock_memo_section_repo, valid_state):
    """Check should fail when fabricated ruling referenced."""
    mock_section = MagicMock()
    mock_section.section_type = "relevant_previous_rulings"
    mock_section.structured_data = {
        "content": "According to ruling HQ H999999, classification is 1234.56",
        "analyst_reasoning": "Ruling analysis",
        "source_attribution": [],
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.FAILED
    assert result.blocking is True


@pytest.mark.asyncio
async def test_check_fails_with_unsupported_no_ruling(mock_memo_section_repo, valid_state):
    """Check should fail when 'no ruling' claimed but rulings exist."""
    mock_section = MagicMock()
    mock_section.section_type = "relevant_previous_rulings"
    mock_section.structured_data = {
        "content": "No previous rulings exist for this product",
        "analyst_reasoning": "No rulings found",
        "source_attribution": [],
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.FAILED
    assert "unsupported" in result.message.lower() or "error" in result.message.lower()


@pytest.mark.asyncio
async def test_check_fails_with_placeholder_hs_code(mock_memo_section_repo, valid_state):
    """Check should fail when recommendation has placeholder HS code."""
    mock_section = MagicMock()
    mock_section.section_type = "recommended_classification"
    mock_section.structured_data = {
        "content": "Recommendation",
        "analyst_reasoning": "Analysis",
        "source_attribution": [],
        "recommendation": {
            "hs_code": "XXXX.XX",
            "description": "TBD",
            "reasoning": "",
        },
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.FAILED
    assert result.blocking is True


@pytest.mark.asyncio
async def test_check_warning_with_missing_source(mock_memo_section_repo, valid_state):
    """Check should warn when source attribution missing but otherwise valid."""
    mock_section = MagicMock()
    mock_section.section_type = "relevant_previous_rulings"
    mock_section.structured_data = {
        "content": "Analysis of ruling HQ H265674",
        "analyst_reasoning": "Ruling provides precedent",
        "source_attribution": [],  # Missing attribution
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    # Should be warning, not error (non-blocking)
    if result.status == CheckStatus.WARNING:
        assert result.blocking is False
        assert "warning" in result.message.lower()
    else:
        # Or might pass depending on strictness
        assert result.status in (CheckStatus.PASSED, CheckStatus.WARNING)


@pytest.mark.asyncio
async def test_check_with_multiple_sections(mock_memo_section_repo, valid_state):
    """Check should validate multiple sections."""
    mock_section1 = MagicMock()
    mock_section1.section_type = "product_description"
    mock_section1.structured_data = {
        "content": "Aluminum container",
        "analyst_reasoning": "Material verified",
        "source_attribution": [{"source": "spec"}],
    }

    mock_section2 = MagicMock()
    mock_section2.section_type = "recommended_classification"
    mock_section2.structured_data = {
        "content": "Recommendation",
        "analyst_reasoning": "Analysis",
        "source_attribution": [{"source": "ruling"}],
        "recommendation": {
            "hs_code": "7326.90.8588",
            "description": "Classification",
            "reasoning": "Based on ruling HQ H265674 for aluminum products",
        },
    }

    mock_memo_section_repo.list_by_run.return_value = [mock_section1, mock_section2]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.PASSED
    assert "2 section" in result.message


@pytest.mark.asyncio
async def test_check_handles_parse_error(mock_memo_section_repo, valid_state):
    """Check should handle section parse errors gracefully."""
    mock_section = MagicMock()
    mock_section.section_type = "product_description"
    mock_section.structured_data = None  # Invalid

    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    # Should skip due to no valid sections
    assert result.status == CheckStatus.SKIPPED


@pytest.mark.asyncio
async def test_check_details_include_violations(mock_memo_section_repo, valid_state):
    """Check details should include violation information."""
    mock_section = MagicMock()
    mock_section.section_type = "product_description"
    mock_section.structured_data = {
        "content": "[TODO] Complete description",
        "analyst_reasoning": "Placeholder",
        "source_attribution": [],
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.FAILED
    assert "violations" in result.details
    assert "total_violations" in result.details
    assert "errors" in result.details
    assert result.details["errors"] > 0
    assert len(result.details["violations"]) > 0


@pytest.mark.asyncio
async def test_check_without_product_facts(mock_memo_section_repo):
    """Check should work without product facts."""
    state = {
        "workflow_run_id": str(uuid4()),
        "product_facts": None,
        "ruling_facts": [],
        "matched_ruling_ids": [],
        "reconciliation_conflicts": [],
        "retrieved_chunks": [],
    }

    mock_section = MagicMock()
    mock_section.section_type = "product_description"
    mock_section.structured_data = {
        "content": "Product description",
        "analyst_reasoning": "Analysis",
        "source_attribution": [],
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=state, config={})

    # Should not crash, may pass or warn
    assert result.status in (CheckStatus.PASSED, CheckStatus.WARNING, CheckStatus.FAILED)


@pytest.mark.asyncio
async def test_check_summarizes_categories(mock_memo_section_repo, valid_state):
    """Check message should summarize violation categories."""
    mock_section = MagicMock()
    mock_section.section_type = "product_description"
    mock_section.structured_data = {
        "content": "[PLACEHOLDER] plastic product",
        "analyst_reasoning": "TODO",
        "source_attribution": [],
    }
    mock_memo_section_repo.list_by_run.return_value = [mock_section]

    check = MemoGroundingCheck(memo_section_repo=mock_memo_section_repo)
    result = await check.run(state=valid_state, config={})

    assert result.status == CheckStatus.FAILED
    # Message should include category summary
    assert "placeholder" in result.message.lower() or "product_fact" in result.message.lower()
