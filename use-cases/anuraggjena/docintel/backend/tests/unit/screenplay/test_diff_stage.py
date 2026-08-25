import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4


def _make_state(items):
    return {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "formatting_items": items,
    }


@pytest.mark.asyncio
async def test_diff_stage_populates_diff_tokens():
    from backend.modules.screenplay.stages.diff import DiffStage
    from backend.repositories.screenplay import FormattingItemRepository

    mock_repo = AsyncMock(spec=FormattingItemRepository)
    mock_repo.update = AsyncMock(return_value=MagicMock())

    items = [
        {"id": str(uuid4()), "element_index": 0, "element_type": "scene_heading",
         "original_text": "int. office", "formatted_text": "INT. OFFICE",
         "change_type": "capitalization", "reason": "", "diff_tokens": [],
         "content_drift": False, "status": "pending", "confidence_score": 1.0},
    ]
    stage = DiffStage(formatting_item_repo=mock_repo, review_repo=None, run_repo=None)
    result = await stage.execute(_make_state(items))

    updated = result["formatting_items"]
    assert len(updated[0]["diff_tokens"]) > 0


@pytest.mark.asyncio
async def test_diff_stage_no_change_item_has_equal_tokens():
    from backend.modules.screenplay.stages.diff import DiffStage
    from backend.repositories.screenplay import FormattingItemRepository

    mock_repo = AsyncMock(spec=FormattingItemRepository)
    mock_repo.update = AsyncMock(return_value=MagicMock())

    items = [
        {"id": str(uuid4()), "element_index": 0, "element_type": "action",
         "original_text": "A man enters.", "formatted_text": "A man enters.",
         "change_type": "no_change", "reason": "", "diff_tokens": [],
         "content_drift": False, "status": "pending", "confidence_score": 1.0},
    ]
    stage = DiffStage(formatting_item_repo=mock_repo, review_repo=None, run_repo=None)
    result = await stage.execute(_make_state(items))

    tokens = result["formatting_items"][0]["diff_tokens"]
    assert all(t["type"] == "equal" for t in tokens)


@pytest.mark.asyncio
async def test_diff_stage_creates_review_and_sets_awaiting_review():
    from backend.modules.screenplay.stages.diff import DiffStage
    from backend.repositories.screenplay import FormattingItemRepository

    mock_repo = AsyncMock(spec=FormattingItemRepository)
    review = MagicMock()
    review.id = uuid4()
    mock_review_repo = AsyncMock()
    mock_review_repo.create = AsyncMock(return_value=review)
    mock_run_repo = AsyncMock()

    items = [
        {"id": str(uuid4()), "element_index": 0, "element_type": "action",
         "original_text": "a", "formatted_text": "A",
         "change_type": "capitalization", "reason": "", "diff_tokens": [],
         "content_drift": False, "status": "pending", "confidence_score": 1.0},
    ]
    state = _make_state(items)
    stage = DiffStage(formatting_item_repo=mock_repo, review_repo=mock_review_repo,
                      run_repo=mock_run_repo)
    result = await stage.execute(state)

    assert result["diff_available"] is True
    mock_review_repo.create.assert_awaited_once()
    mock_repo.attach_review.assert_awaited_once()
    mock_run_repo.update.assert_awaited_once()
