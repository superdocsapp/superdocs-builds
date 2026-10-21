import pytest
from unittest.mock import AsyncMock, patch

from backend.modules.tariff.stages.extract_product_facts import ExtractProductFactsStage
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.memo_types import ProductFacts


def _base_state(**kwargs):
    defaults = {
        "workflow_run_id": "00000000-0000-0000-0000-000000000001",
        "workspace_id": "00000000-0000-0000-0000-000000000002",
    }
    defaults.update(kwargs)
    return TariffWorkflowState(**defaults)


@pytest.mark.asyncio
async def test_extract_product_facts_from_document():
    stage = ExtractProductFactsStage()
    state = _base_state(
        document_content="Product: Steel Widget. Material: Stainless steel 304.",
    )
    mock_facts = ProductFacts(
        product_name="Steel Widget",
        material_composition="Stainless steel 304",
    )
    with patch.object(stage.llm, "generate_structured", new=AsyncMock(return_value=mock_facts)):
        result = await stage.execute(state)
    assert result["product_facts"].product_name == "Steel Widget"
    assert result["extract_product_completed"] is True


@pytest.mark.asyncio
async def test_extract_blocks_without_document_content():
    stage = ExtractProductFactsStage()
    state = _base_state()
    with pytest.raises(ValueError, match="No document content"):
        await stage.execute(state)


@pytest.mark.asyncio
async def test_prior_knowledge_included_in_prompt():
    stage = ExtractProductFactsStage()
    state = _base_state(
        document_content="Product spec content",
        prior_knowledge="Prior memo classified widgets under 7326.90",
    )
    with patch.object(stage.llm, "generate_structured", new=AsyncMock(return_value=ProductFacts())) as mock_gen:
        await stage.execute(state)
    messages = mock_gen.call_args.kwargs["messages"]
    user_content = next(m.content for m in messages if m.role == "user")
    assert "Prior memo classified widgets" in user_content
