import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def _make_item(status, element_type="scene_heading", original="int. office", formatted="INT. OFFICE",
               reviewer_comment=None):
    return {
        "id": str(uuid4()),
        "element_index": 0,
        "element_type": element_type,
        "original_text": original,
        "formatted_text": formatted,
        "change_type": "capitalization",
        "reason": "",
        "diff_tokens": [],
        "content_drift": False,
        "status": status,
        "reviewer_comment": reviewer_comment,
        "confidence_score": 1.0,
    }


def _make_state(items):
    return {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "formatting_items": items,
    }


@pytest.mark.asyncio
async def test_regenerate_skips_approved_items():
    from backend.modules.screenplay.stages.regenerate import RegenerateStage
    from backend.repositories.screenplay import FormattingItemRepository
    from backend.core.llm.provider import LLMProvider

    mock_llm = AsyncMock(spec=LLMProvider)
    mock_repo = AsyncMock(spec=FormattingItemRepository)
    mock_repo.update = AsyncMock(return_value=MagicMock())

    approved = _make_item("approved")
    state = _make_state([approved])

    stage = RegenerateStage(llm_provider=mock_llm, formatting_item_repo=mock_repo)
    result = await stage.execute(state)

    # LLM should not be called for approved items
    mock_llm.generate.assert_not_called()
    assert result["formatting_items"][0]["status"] == "approved"


@pytest.mark.asyncio
async def test_regenerate_reprocesses_rejected_items():
    from backend.modules.screenplay.stages.regenerate import RegenerateStage
    from backend.repositories.screenplay import FormattingItemRepository
    from backend.core.llm.provider import LLMProvider

    mock_llm = AsyncMock(spec=LLMProvider)
    mock_response = MagicMock()
    mock_response.content = "INT. CAFE - DAY"
    mock_llm.generate = AsyncMock(return_value=mock_response)

    mock_repo = AsyncMock(spec=FormattingItemRepository)
    mock_repo.update = AsyncMock(return_value=MagicMock())

    rejected = _make_item("rejected", element_type="scene_heading",
                          original="int. cafe - day", formatted="INT. CAFE - DAY",
                          reviewer_comment="Please use standard format")
    state = _make_state([rejected])

    stage = RegenerateStage(llm_provider=mock_llm, formatting_item_repo=mock_repo)
    result = await stage.execute(state)

    # LLM called for rejected item
    mock_llm.generate.assert_called_once()
    item = result["formatting_items"][0]
    assert item["status"] == "pending"  # reset for re-review


@pytest.mark.asyncio
async def test_regenerate_increments_regeneration_count():
    from backend.modules.screenplay.stages.regenerate import RegenerateStage
    from backend.repositories.screenplay import FormattingItemRepository
    from backend.core.llm.provider import LLMProvider

    mock_llm = AsyncMock(spec=LLMProvider)
    mock_repo = AsyncMock(spec=FormattingItemRepository)

    state = _make_state([_make_item("approved")])
    state["regeneration_count"] = 1

    stage = RegenerateStage(llm_provider=mock_llm, formatting_item_repo=mock_repo)
    result = await stage.execute(state)

    assert result["regeneration_count"] == 2
