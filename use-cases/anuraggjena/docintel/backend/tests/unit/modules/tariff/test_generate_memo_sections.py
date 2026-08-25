import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from backend.modules.tariff.stages.generate_memo_sections import GenerateMemoSectionsStage
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.modules.tariff.memo_types import ProductFacts, MemoSectionOutput


def _base_state(**kwargs):
    defaults = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": "00000000-0000-0000-0000-000000000002",
    }
    defaults.update(kwargs)
    return TariffWorkflowState(**defaults)


@pytest.fixture
def mock_memo_service():
    service = AsyncMock()
    section = MagicMock(id=uuid4())
    claim = MagicMock(id=uuid4())
    service.create_section_with_claim = AsyncMock(return_value=(section, claim))
    # Mock section repository for idempotency checks
    service._section_repo = AsyncMock()
    service._section_repo.get_by_run_and_type = AsyncMock(return_value=None)
    service._section_repo.update = AsyncMock()
    service._claim_repo = AsyncMock()
    service._claim_repo.list_by_run = AsyncMock(return_value=[])
    return service


@pytest.mark.asyncio
async def test_generates_memo_sections(mock_memo_service):
    stage = GenerateMemoSectionsStage(memo_section_service=mock_memo_service)
    state = _base_state(
        product_facts=ProductFacts(product_name="Widget"),
        prior_knowledge="Prior memo used GRI 3(b)",
        prior_knowledge_entries=["entry-1"],
    )
    output = MemoSectionOutput(
        content="Section content",
        analyst_reasoning="Analysis text",
        adopted_knowledge_entry_ids=["entry-1"],
    )
    with patch.object(stage.llm, "generate_structured", new=AsyncMock(return_value=output)):
        result = await stage.execute(state)
    assert result["generate_memo_completed"] is True
    assert len(result["memo_section_ids"]) > 0
    assert mock_memo_service.create_section_with_claim.call_count > 0


@pytest.mark.asyncio
async def test_analyst_reasoning_separated_from_source(mock_memo_service):
    stage = GenerateMemoSectionsStage(memo_section_service=mock_memo_service)
    state = _base_state(product_facts=ProductFacts(product_name="Widget"))
    output = MemoSectionOutput(
        content='> "Quoted ruling"\n\nAnalysis conclusion.',
        analyst_reasoning="Analysis conclusion.",
        source_attribution=[{"type": "ruling", "id": "HQ-123", "excerpt": "Quoted ruling"}],
    )
    with patch.object(stage.llm, "generate_structured", new=AsyncMock(return_value=output)):
        await stage.execute(state)
    call_kwargs = mock_memo_service.create_section_with_claim.call_args.kwargs
    assert call_kwargs["analyst_reasoning"] == "Analysis conclusion."
    assert call_kwargs["source_attribution"][0]["excerpt"] == "Quoted ruling"


@pytest.mark.asyncio
async def test_regenerates_only_marked_sections(mock_memo_service):
    stage = GenerateMemoSectionsStage(memo_section_service=mock_memo_service)
    state = _base_state(
        product_facts=ProductFacts(product_name="Widget"),
        sections_to_regenerate=["classification_analysis"],
        image_document_ids=["img-1"],
    )
    output = MemoSectionOutput(content="text", analyst_reasoning="reasoning")
    with patch.object(stage.llm, "generate_structured", new=AsyncMock(return_value=output)) as mock_gen:
        await stage.execute(state)
    generated_types = {
        call.kwargs.get("section_type") or call.args[1] if len(call.args) > 1 else call.kwargs["section_type"]
        for call in mock_memo_service.create_section_with_claim.call_args_list
        if (call.kwargs.get("status") or "pending") != "skipped"
    }
    # LLM called for classification_analysis and executive_summary only
    assert mock_gen.call_count == 2
