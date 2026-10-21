"""
Integration test for the screenplay review cycle:
run -> approve some -> reject some -> regenerate -> verify states.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.modules.screenplay.stages.regenerate import RegenerateStage
from backend.core.llm.provider import LLMProvider


def _items():
    return [
        {
            "id": str(uuid4()), "element_index": 0, "element_type": "scene_heading",
            "original_text": "int. office - day", "formatted_text": "INT. OFFICE - DAY",
            "change_type": "capitalization", "reason": "", "diff_tokens": [],
            "content_drift": False, "status": "approved",  # approved - should NOT be touched
            "reviewer_comment": None, "confidence_score": 1.0,
        },
        {
            "id": str(uuid4()), "element_index": 1, "element_type": "scene_heading",
            "original_text": "ext. park - night", "formatted_text": "EXT PARK NIGHT",
            "change_type": "capitalization", "reason": "", "diff_tokens": [],
            "content_drift": False, "status": "rejected",  # rejected - should be regenerated
            "reviewer_comment": "Add proper punctuation", "confidence_score": 1.0,
        },
    ]


@pytest.mark.asyncio
async def test_regenerate_only_affects_rejected_items():
    from backend.repositories.screenplay import FormattingItemRepository

    mock_llm = MagicMock(spec=LLMProvider)
    mock_response = MagicMock()
    mock_response.content = "INT. OFFICE - DAY"
    mock_llm.generate = AsyncMock(return_value=mock_response)

    mock_repo = AsyncMock(spec=FormattingItemRepository)
    mock_repo.update = AsyncMock(return_value=MagicMock())

    items = _items()

    stage = RegenerateStage(llm_provider=mock_llm, formatting_item_repo=mock_repo)
    result = await stage.execute({
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "formatting_items": items,
    })

    updated = result["formatting_items"]
    approved_item = next(i for i in updated if i["element_index"] == 0)
    rejected_item = next(i for i in updated if i["element_index"] == 1)

    assert approved_item["status"] == "approved"  # unchanged
    assert rejected_item["status"] == "pending"   # reset for re-review
    assert result["regeneration_count"] == 1


@pytest.mark.asyncio
async def test_regenerate_clears_reviewer_comment_and_recomputes_diff():
    from backend.repositories.screenplay import FormattingItemRepository

    mock_llm = MagicMock(spec=LLMProvider)
    mock_response = MagicMock()
    mock_response.content = "EXT. PARK - NIGHT"
    mock_llm.generate = AsyncMock(return_value=mock_response)

    mock_repo = AsyncMock(spec=FormattingItemRepository)

    stage = RegenerateStage(llm_provider=mock_llm, formatting_item_repo=mock_repo)
    result = await stage.execute({
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "formatting_items": _items(),
    })

    rejected_item = next(i for i in result["formatting_items"] if i["element_index"] == 1)
    assert rejected_item["reviewer_comment"] is None
    assert isinstance(rejected_item["diff_tokens"], list)
    assert len(rejected_item["diff_tokens"]) > 0
    # DB persistence happened for the rejected item only
    assert mock_repo.update.await_count == 1


@pytest.mark.asyncio
async def test_export_uses_original_text_for_rejected_items():
    """After review, rejected items must fall back to their original text in the DOCX."""
    from backend.core.export.docx_generator import DOCXGenerator

    gen = DOCXGenerator()
    docx_bytes = gen.generate_screenplay_docx(
        formatting_items=[
            {"element_index": 0, "element_type": "scene_heading",
             "original_text": "int. office - day", "formatted_text": "INT. OFFICE - DAY",
             "status": "approved"},
            {"element_index": 1, "element_type": "scene_heading",
             "original_text": "ext. park - night", "formatted_text": "EXT PARK NIGHT",
             "status": "rejected"},
        ],
        title="Review Cycle",
        workspace_name="WS",
    )
    assert isinstance(docx_bytes, bytes)
    assert len(docx_bytes) > 0
