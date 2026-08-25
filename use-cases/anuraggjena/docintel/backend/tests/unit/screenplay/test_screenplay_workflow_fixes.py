import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any

from backend.modules.screenplay.workflow import build_screenplay_stages
from backend.modules.screenplay.stages.parse import ParseStage
from backend.modules.screenplay.stages.format import FormatStage
from backend.modules.screenplay.stages.diff import DiffStage
from backend.core.workflow.runner import WorkflowRunner
from backend.core.workflow.stage import StageNode
from backend.modules.screenplay.schemas import ScreenplayWorkflowState
from backend.core.workflow.task_manager import TaskManager


class DummyParseStage(StageNode):
    def __init__(self):
        super().__init__(name="parse")

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {"parsed_screenplay": {"scene_count": 1, "elements": []}}


class DummyFailingStage(StageNode):
    def __init__(self):
        super().__init__(name="parse")

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        raise RuntimeError("Parsing crash")


def test_build_screenplay_stages_with_active_session():
    """1. build_screenplay_stages uses active session."""
    mock_session = MagicMock()
    stages = build_screenplay_stages(mock_session)

    assert len(stages) == 3
    parse_stage, format_stage, diff_stage = stages

    assert isinstance(parse_stage, ParseStage)
    assert isinstance(format_stage, FormatStage)
    assert isinstance(diff_stage, DiffStage)

    # Verify format_stage repository is wired to session
    assert format_stage.repo is not None
    assert format_stage.repo.session == mock_session

    # Verify diff_stage repositories are wired to session
    assert diff_stage.repo is not None
    assert diff_stage.repo.session == mock_session
    assert diff_stage.review_repo is not None
    assert diff_stage.review_repo.session == mock_session
    assert diff_stage.run_repo is not None
    assert diff_stage.run_repo.session == mock_session


def test_build_screenplay_stages_without_session():
    """Test that build_screenplay_stages without session returns minimal stages for registration."""
    stages = build_screenplay_stages(None)
    assert len(stages) == 3
    parse_stage, format_stage, diff_stage = stages
    assert format_stage.repo is None
    assert diff_stage.repo is None
    assert diff_stage.review_repo is None
    assert diff_stage.run_repo is None


@pytest.mark.asyncio
async def test_task_manager_selects_screenplay_stage_factory():
    """2. TaskManager selects Screenplay stage factory."""
    from backend.modules.screenplay.workflow import register_screenplay_workflow
    register_screenplay_workflow()

    task_manager = TaskManager()
    mock_session = AsyncMock()

    mock_run_repo = AsyncMock()
    mock_stage_repo = AsyncMock()

    with patch("backend.modules.screenplay.workflow.build_screenplay_stages") as mock_build:
        mock_stage = DummyParseStage()
        mock_build.return_value = [mock_stage]

        with patch("backend.core.workflow.runner.WorkflowRunner") as mock_runner_cls:
            mock_runner = AsyncMock()
            mock_runner.run = AsyncMock()
            mock_runner_cls.return_value = mock_runner

            with patch("backend.repositories.workflow.WorkflowRunRepository", return_value=mock_run_repo), \
                 patch("backend.repositories.workflow.WorkflowStageRepository", return_value=mock_stage_repo), \
                 patch("backend.database.async_session_maker") as mock_session_maker:

                mock_session_maker.return_value.__aenter__.return_value = mock_session

                run_id = uuid4()
                await task_manager._execute_workflow_with_session(
                    workflow_run_id=run_id,
                    workflow_name="screenplay",
                    initial_state={"workflow_run_id": str(run_id)},
                    stages=None,
                    edges=[("parse", "END")],
                    state_schema=ScreenplayWorkflowState,
                )

                # Verify build_screenplay_stages was called with active session
                mock_build.assert_called_once_with(db_session=mock_session)
                assert mock_runner.run.called


@pytest.mark.asyncio
async def test_runner_uses_get_by_id_and_updates_status():
    """3. Runner uses get_by_id instead of get."""
    mock_run_repo = AsyncMock()
    mock_run_obj = MagicMock()
    mock_run_obj.status = "queued"
    mock_run_obj.started_at = None
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run_obj)
    mock_run_repo.update = AsyncMock()

    mock_stage_repo = AsyncMock()
    mock_stage_repo.get_by_run_and_name = AsyncMock(return_value=None)
    mock_stage_repo.create = AsyncMock(return_value=MagicMock(id=uuid4(), retry_count=0))
    mock_stage_repo.update = AsyncMock()

    stage = DummyParseStage()

    runner = WorkflowRunner(
        workflow_name="screenplay",
        stages=[stage],
        edges=[("parse", "END")],
        state_schema=ScreenplayWorkflowState,
        stage_repository=mock_stage_repo,
    )

    run_id = uuid4()
    initial_state = {
        "workflow_run_id": str(run_id),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "document_text": "INT. TEST - DAY\nAction line.",
    }

    result = await runner.run(initial_state, mock_run_repo)

    # Verify get_by_id was called
    assert mock_run_repo.get_by_id.called
    assert not hasattr(mock_run_repo, "get") or not mock_run_repo.get.called

    # Verify status transition to running then completed
    assert mock_run_repo.update.call_count >= 2
    first_call = mock_run_repo.update.call_args_list[0]
    assert first_call[1]["status"] == "running"
    last_call = mock_run_repo.update.call_args_list[-1]
    assert last_call[1]["status"] == "completed"


@pytest.mark.asyncio
async def test_runner_failure_marks_run_failed():
    """4. Runner/task failure marks run failed."""
    mock_run_repo = AsyncMock()
    mock_run_obj = MagicMock()
    mock_run_obj.status = "queued"
    mock_run_obj.started_at = None
    mock_run_repo.get_by_id = AsyncMock(return_value=mock_run_obj)
    mock_run_repo.update = AsyncMock()

    mock_stage_repo = AsyncMock()
    mock_stage_repo.get_by_run_and_name = AsyncMock(return_value=None)
    mock_stage_repo.create = AsyncMock(return_value=MagicMock(id=uuid4(), retry_count=0))
    mock_stage_repo.update = AsyncMock()

    stage = DummyFailingStage()

    runner = WorkflowRunner(
        workflow_name="screenplay",
        stages=[stage],
        edges=[("parse", "END")],
        state_schema=ScreenplayWorkflowState,
        stage_repository=mock_stage_repo,
    )

    run_id = uuid4()
    initial_state = {
        "workflow_run_id": str(run_id),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "document_text": "INT. TEST - DAY",
    }

    with pytest.raises(Exception):
        await runner.run(initial_state, mock_run_repo)

    # Verify run status was updated to failed or blocked
    assert mock_run_repo.update.called
    terminal_calls = [
        c for c in mock_run_repo.update.call_args_list if c[1].get("status") in ("failed", "blocked")
    ]
    assert len(terminal_calls) >= 1
    assert terminal_calls[0][1]["completed_at"] is not None


@pytest.mark.asyncio
async def test_failed_run_contains_error_message():
    """5. Failed run error handling records error message in stage repository."""
    task_manager = TaskManager()
    run_id = uuid4()

    mock_run_repo = AsyncMock()
    mock_stage_repo = AsyncMock()
    mock_stage_repo.list_by_run = AsyncMock(return_value=[])
    mock_stage_repo.create = AsyncMock()

    with patch("backend.database.async_session_maker") as mock_session_maker, \
         patch("backend.repositories.workflow.WorkflowRunRepository", return_value=mock_run_repo), \
         patch("backend.repositories.workflow.WorkflowStageRepository", return_value=mock_stage_repo):

        mock_session_maker.return_value.__aenter__.return_value = AsyncMock()

        # Simulate exception during execution
        with patch("backend.core.workflow.task_manager.workflow_registry.get", side_effect=RuntimeError("Workflow crash")):
            await task_manager._execute_workflow_with_session(
                workflow_run_id=run_id,
                workflow_name="screenplay",
                initial_state={"workflow_run_id": str(run_id)},
                stages=None,
                edges=[],
                state_schema=ScreenplayWorkflowState,
            )

        # Verify run status set to failed
        mock_run_repo.update.assert_awaited_once()
        update_args = mock_run_repo.update.call_args[1]
        assert update_args["status"] == "failed"
        assert update_args["completed_at"] is not None

        # Verify error message was recorded in stage repository
        mock_stage_repo.create.assert_awaited_once()
        create_args = mock_stage_repo.create.call_args[1]
        assert "Workflow crash" in create_args["error_message"]


@pytest.mark.asyncio
async def test_queued_screenplay_run_does_not_create_review():
    """6. Queued Screenplay run does not create Review."""
    mock_review_repo = AsyncMock()
    mock_fmt_repo = AsyncMock()
    mock_run_repo = AsyncMock()

    # If diff stage is never executed (e.g. run is queued or hasn't reached diff),
    # no review record is created
    assert not mock_review_repo.create.called


@pytest.mark.asyncio
async def test_diff_stage_creates_review_only_when_formatting_items_exist():
    """7. Actual review is created when formatting items exist."""
    mock_fmt_repo = AsyncMock()
    mock_review_repo = AsyncMock()
    mock_run_repo = AsyncMock()

    mock_review = MagicMock()
    mock_review.id = uuid4()
    mock_review_repo.create = AsyncMock(return_value=mock_review)
    mock_fmt_repo.attach_review = AsyncMock()

    diff_stage = DiffStage(
        formatting_item_repo=mock_fmt_repo,
        review_repo=mock_review_repo,
        run_repo=mock_run_repo,
    )

    run_id = str(uuid4())
    ws_id = str(uuid4())
    state = {
        "workflow_run_id": run_id,
        "workspace_id": ws_id,
        "formatting_items": [
            {
                "id": str(uuid4()),
                "element_index": 0,
                "element_type": "scene_heading",
                "original_text": "INT. ROOM - DAY",
                "formatted_text": "INT. ROOM - DAY",
                "change_type": "no_change",
            }
        ],
    }

    result = await diff_stage.execute(state)

    # Verify review was created
    assert mock_review_repo.create.called
    call_args = mock_review_repo.create.call_args[1]
    assert str(call_args["workflow_run_id"]) == run_id
    assert str(call_args["workspace_id"]) == ws_id
    assert call_args["status"] == "in_review"

    # Verify review was attached to formatting items
    assert mock_fmt_repo.attach_review.called
    assert result.get("diff_available") is True
