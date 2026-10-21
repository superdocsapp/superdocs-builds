"""
Integration test for the screenplay workflow.

LLM calls are mocked. WorkflowRunner, stages, and state passing use real code.
FormattingItemRepository is mocked (no real DB needed).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.core.workflow.runner import WorkflowRunner
from backend.modules.screenplay.stages.parse import ParseStage
from backend.modules.screenplay.stages.format import FormatStage
from backend.modules.screenplay.stages.diff import DiffStage
from backend.modules.screenplay.schemas import ScreenplayWorkflowState
from backend.core.llm.provider import LLMProvider


SAMPLE_SCREENPLAY = """INT. COFFEE SHOP - DAY

A barista wipes down the counter.

SARAH
Can I get a latte?

BARISTA
(smiling)
Coming right up.

CUT TO:
"""


def _make_stage_repo():
    repo = AsyncMock()
    repo.get_by_run_and_name = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=MagicMock(id=uuid4()))
    repo.update = AsyncMock(return_value=MagicMock())
    return repo


def _make_run_repo():
    repo = AsyncMock()
    repo.update = AsyncMock(return_value=MagicMock())
    return repo


def _make_item_repo():
    repo = AsyncMock()
    item = MagicMock()
    item.id = uuid4()
    repo.create = AsyncMock(return_value=item)
    repo.update = AsyncMock(return_value=item)
    repo.attach_review = AsyncMock()
    return repo


def _make_review_repo():
    repo = AsyncMock()
    review = MagicMock()
    review.id = uuid4()
    repo.create = AsyncMock(return_value=review)
    return repo


def _build_runner(item_repo, review_repo, run_repo, stage_repo, mock_llm):
    parse_stage = ParseStage(llm_provider=mock_llm)
    format_stage = FormatStage(llm_provider=mock_llm, formatting_item_repo=item_repo)
    diff_stage = DiffStage(
        formatting_item_repo=item_repo,
        review_repo=review_repo,
        run_repo=run_repo,
    )
    return WorkflowRunner(
        workflow_name="screenplay",
        stages=[parse_stage, format_stage, diff_stage],
        edges=[("parse", "format"), ("format", "diff"), ("diff", "END")],
        state_schema=ScreenplayWorkflowState,
        stage_repository=stage_repo,
    )


@pytest.mark.asyncio
async def test_screenplay_workflow_end_to_end():
    mock_llm = MagicMock(spec=LLMProvider)
    # LLM not called for clean script
    mock_llm.generate = AsyncMock()

    item_repo = _make_item_repo()
    review_repo = _make_review_repo()
    run_repo = _make_run_repo()
    stage_repo = _make_stage_repo()

    runner = _build_runner(item_repo, review_repo, run_repo, stage_repo, mock_llm)

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "document_text": SAMPLE_SCREENPLAY,
        "status": "queued",
    }

    final_state = await runner.run(initial_state, run_repo)

    assert "formatting_items" in final_state
    items = final_state["formatting_items"]
    assert len(items) > 0
    assert final_state.get("diff_available") is True

    # All items should have diff_tokens
    for item in items:
        assert "diff_tokens" in item
        assert isinstance(item["diff_tokens"], list)

    # scene heading should be capitalised
    scene = next((i for i in items if i["element_type"] == "scene_heading"), None)
    assert scene is not None
    assert scene["formatted_text"] == "INT. COFFEE SHOP - DAY"


@pytest.mark.asyncio
async def test_screenplay_workflow_creates_review_and_awaits_review():
    mock_llm = MagicMock(spec=LLMProvider)
    mock_llm.generate = AsyncMock()

    item_repo = _make_item_repo()
    review_repo = _make_review_repo()
    run_repo = _make_run_repo()
    stage_repo = _make_stage_repo()

    runner = _build_runner(item_repo, review_repo, run_repo, stage_repo, mock_llm)

    await runner.run({
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "document_text": SAMPLE_SCREENPLAY,
        "status": "queued",
    }, run_repo)

    review_repo.create.assert_awaited_once()
    item_repo.attach_review.assert_awaited_once()


@pytest.mark.asyncio
async def test_screenplay_workflow_empty_document():
    mock_llm = MagicMock(spec=LLMProvider)
    mock_llm.generate = AsyncMock()
    item_repo = _make_item_repo()
    review_repo = _make_review_repo()
    run_repo = _make_run_repo()
    stage_repo = _make_stage_repo()

    runner = _build_runner(item_repo, review_repo, run_repo, stage_repo, mock_llm)

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "document_text": "",
        "status": "queued",
    }

    final_state = await runner.run(initial_state, run_repo)
    assert final_state["formatting_items"] == []
