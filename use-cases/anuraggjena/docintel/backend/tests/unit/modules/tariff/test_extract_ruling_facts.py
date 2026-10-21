import pytest
from unittest.mock import AsyncMock, patch

from backend.modules.tariff.stages.extract_ruling_facts import ExtractRulingFactsStage
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.memo_types import RulingFacts, RulingFactsList


def _base_state(**kwargs):
    defaults = {
        "workflow_run_id": "00000000-0000-0000-0000-000000000001",
        "workspace_id": "00000000-0000-0000-0000-000000000002",
    }
    defaults.update(kwargs)
    return TariffWorkflowState(**defaults)


@pytest.mark.asyncio
async def test_extract_ruling_facts_skips_when_no_rulings():
    stage = ExtractRulingFactsStage()
    state = _base_state(has_ruling_documents=False)
    result = await stage.execute(state)
    assert result["ruling_facts"] == []
    assert result["extract_ruling_completed"] is True


@pytest.mark.asyncio
async def test_extract_ruling_facts_grounded():
    stage = ExtractRulingFactsStage()
    state = _base_state(
        has_ruling_documents=True,
        ruling_content_map={"ruling-1": "Ruling HQ H265674: classified under 7326.90.8588"},
    )
    mock_result = RulingFactsList(
        rulings=[RulingFacts(
            ruling_number="HQ H265674",
            issuing_authority="US CBP",
            applicable_classification="7326.90.8588",
        )]
    )
    with patch.object(stage.llm, "generate_structured", new=AsyncMock(return_value=mock_result)):
        result = await stage.execute(state)
    assert len(result["ruling_facts"]) == 1
    assert result["ruling_facts"][0].ruling_number == "HQ H265674"
    assert result["ruling_facts"][0].document_id == "ruling-1"
