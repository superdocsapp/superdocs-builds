"""Unit tests for workflow run lifecycle endpoints (Replay, Kill, Resume)"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import HTTPException, BackgroundTasks

from backend.api.v1.runs import replay_run, cancel_run, resume_run
from backend.models.workflow import WorkflowRun, Workflow


@pytest.fixture
def workspace_id():
    return uuid4()


@pytest.fixture
def run_id():
    return uuid4()


@pytest.fixture
def mock_workflow():
    wf = MagicMock(spec=Workflow)
    wf.id = uuid4()
    wf.slug = "tariff_classification"
    return wf


@pytest.fixture
def mock_run(workspace_id, run_id, mock_workflow):
    run = MagicMock(spec=WorkflowRun)
    run.id = run_id
    run.workspace_id = workspace_id
    run.workflow_id = mock_workflow.id
    run.workflow_version = "1.0.0"
    run.status = "completed"
    run.current_stage = None
    run.version_number = 1
    run.created_by = "test-user"
    run.started_at = datetime.now(timezone.utc)
    run.completed_at = datetime.now(timezone.utc)
    run.created_at = datetime.now(timezone.utc)
    return run


@pytest.fixture
def mock_service():
    return AsyncMock()


@pytest.fixture
def mock_db(mock_workflow):
    db = AsyncMock()
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=mock_workflow)
    stage_repo = MagicMock()
    stage_repo.list_by_run = AsyncMock(return_value=[])
    with patch("backend.api.v1.runs.WorkflowRepository", return_value=repo), \
         patch("backend.api.v1.runs.WorkflowStageRepository", return_value=stage_repo):
        yield db


# -----------------------------------------------------------------------------
# Replay Endpoint Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_replay_run_success(workspace_id, run_id, mock_run, mock_service, mock_workflow, mock_db):
    """Test replaying an existing run creates a new run with independent ID and starts execution."""
    new_run_id = uuid4()
    doc_id = uuid4()
    
    new_run = MagicMock(spec=WorkflowRun)
    new_run.id = new_run_id
    new_run.workspace_id = workspace_id
    new_run.workflow_id = mock_workflow.id
    new_run.workflow_version = "1.0.0"
    new_run.status = "queued"
    new_run.current_stage = None
    new_run.version_number = 1
    new_run.created_by = "test-user"
    new_run.started_at = None
    new_run.completed_at = None
    new_run.created_at = datetime.now(timezone.utc)

    mock_service.replay_run = AsyncMock(return_value=(new_run, doc_id))
    mock_service.build_initial_state = AsyncMock(return_value={"workflow_run_id": str(new_run_id)})

    bg_tasks = BackgroundTasks()

    response = await replay_run(
        workspace_id=workspace_id,
        run_id=run_id,
        background_tasks=bg_tasks,
        run=mock_run,
        service=mock_service,
        db=mock_db,
    )

    assert response["id"] == new_run_id
    assert response["workspace_id"] == workspace_id
    assert response["workflow_slug"] == "tariff_classification"
    mock_service.replay_run.assert_awaited_once_with(
        workspace_id=workspace_id,
        original_run_id=run_id,
        created_by="test-user",
    )
    mock_service.build_initial_state.assert_awaited_once_with(new_run_id, doc_id)
    assert len(bg_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_replay_run_workspace_mismatch(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test replay fails when workspace_id does not match the run's workspace."""
    other_workspace_id = uuid4()
    bg_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await replay_run(
            workspace_id=other_workspace_id,
            run_id=run_id,
            background_tasks=bg_tasks,
            run=mock_run,
            service=mock_service,
            db=mock_db,
        )

    assert exc_info.value.status_code == 404


# -----------------------------------------------------------------------------
# Kill / Cancel Endpoint Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_run_success(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test cancelling an active run."""
    mock_run.status = "running"
    
    cancelled_run = MagicMock(spec=WorkflowRun)
    cancelled_run.id = run_id
    cancelled_run.workspace_id = workspace_id
    cancelled_run.workflow_id = mock_run.workflow_id
    cancelled_run.workflow_version = "1.0.0"
    cancelled_run.status = "cancelled"
    cancelled_run.current_stage = None
    cancelled_run.version_number = 1
    cancelled_run.created_by = "test-user"
    cancelled_run.started_at = mock_run.started_at
    cancelled_run.completed_at = datetime.now(timezone.utc)
    cancelled_run.created_at = mock_run.created_at

    # First get_run returns running, second get_run after cancel returns cancelled
    mock_service.get_run = AsyncMock(side_effect=[mock_run, cancelled_run])
    mock_service.cancel_run = AsyncMock(return_value=True)

    response = await cancel_run(
        workspace_id=workspace_id,
        run_id=run_id,
        run=mock_run,
        service=mock_service,
        db=mock_db,
    )

    assert response["id"] == run_id
    assert response["status"] == "cancelled"
    mock_service.cancel_run.assert_awaited_once_with(run_id)


@pytest.mark.asyncio
async def test_cancel_run_conflict_on_terminal(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test cancelling a completed run raises 409 Conflict."""
    mock_run.status = "completed"
    mock_service.get_run = AsyncMock(return_value=mock_run)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_run(
            workspace_id=workspace_id,
            run_id=run_id,
            run=mock_run,
            service=mock_service,
            db=mock_db,
        )

    assert exc_info.value.status_code == 409


# -----------------------------------------------------------------------------
# Resume Endpoint Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_run_waiting_success(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test resuming a waiting run when resumable."""
    mock_run.status = "waiting"
    mock_service.is_run_resumable = AsyncMock(return_value=True)
    bg_tasks = BackgroundTasks()

    response = await resume_run(
        workspace_id=workspace_id,
        run_id=run_id,
        background_tasks=bg_tasks,
        run=mock_run,
        service=mock_service,
        db=mock_db,
    )

    assert response["id"] == run_id
    mock_service.is_run_resumable.assert_awaited_once_with(mock_run)
    assert len(bg_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_resume_cancelled_run_with_checkpoint_success(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test resuming a cancelled run that has a valid checkpoint."""
    mock_run.status = "cancelled"
    mock_service.is_run_resumable = AsyncMock(return_value=True)
    bg_tasks = BackgroundTasks()

    response = await resume_run(
        workspace_id=workspace_id,
        run_id=run_id,
        background_tasks=bg_tasks,
        run=mock_run,
        service=mock_service,
        db=mock_db,
    )

    assert response["id"] == run_id
    mock_service.is_run_resumable.assert_awaited_once_with(mock_run)
    assert len(bg_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_resume_interrupted_run_with_checkpoint_success(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test resuming an interrupted/failed run that has a valid checkpoint."""
    mock_run.status = "failed"
    mock_service.is_run_resumable = AsyncMock(return_value=True)
    bg_tasks = BackgroundTasks()

    response = await resume_run(
        workspace_id=workspace_id,
        run_id=run_id,
        background_tasks=bg_tasks,
        run=mock_run,
        service=mock_service,
        db=mock_db,
    )

    assert response["id"] == run_id
    mock_service.is_run_resumable.assert_awaited_once_with(mock_run)
    assert len(bg_tasks.tasks) == 1


@pytest.mark.asyncio
async def test_resume_completed_run_raises_conflict(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test resuming a completed run raises 409 Conflict because completed runs are not resumable."""
    mock_run.status = "completed"
    mock_service.is_run_resumable = AsyncMock(return_value=False)
    bg_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await resume_run(
            workspace_id=workspace_id,
            run_id=run_id,
            background_tasks=bg_tasks,
            run=mock_run,
            service=mock_service,
            db=mock_db,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_resume_no_checkpoint_raises_conflict(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test resuming a run without any valid checkpoint raises 409 Conflict."""
    mock_run.status = "cancelled"
    mock_service.is_run_resumable = AsyncMock(return_value=False)
    bg_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await resume_run(
            workspace_id=workspace_id,
            run_id=run_id,
            background_tasks=bg_tasks,
            run=mock_run,
            service=mock_service,
            db=mock_db,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_resume_run_conflict_on_running(workspace_id, run_id, mock_run, mock_service, mock_db):
    """Test resuming an actively running run raises 409 Conflict."""
    mock_run.status = "running"
    mock_service.is_run_resumable = AsyncMock(return_value=False)
    bg_tasks = BackgroundTasks()

    with pytest.raises(HTTPException) as exc_info:
        await resume_run(
            workspace_id=workspace_id,
            run_id=run_id,
            background_tasks=bg_tasks,
            run=mock_run,
            service=mock_service,
            db=mock_db,
        )

    assert exc_info.value.status_code == 409


# -----------------------------------------------------------------------------
# WorkflowService.is_run_resumable & _attach_slugs Tests
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_is_run_resumable_cancelled_with_checkpoint():
    """Cancelled run with valid checkpoint in completed stage is resumable."""
    from backend.services.workflow import WorkflowService
    from backend.models.workflow import WorkflowStage
    import json

    stage_repo = AsyncMock()
    stage = MagicMock(spec=WorkflowStage)
    stage.status = "completed"
    stage.checkpoint_data = json.dumps({"foo": "bar"})
    stage_repo.list_by_run = AsyncMock(return_value=[stage])

    service = WorkflowService(
        workflow_repository=AsyncMock(),
        run_repository=AsyncMock(),
        stage_repository=stage_repo,
        document_repository=AsyncMock(),
        storage=AsyncMock(),
    )

    run = MagicMock(spec=WorkflowRun)
    run.id = uuid4()
    run.status = "cancelled"

    assert await service.is_run_resumable(run) is True


@pytest.mark.asyncio
async def test_is_run_resumable_interrupted_failed_with_checkpoint():
    """Interrupted/failed run with valid checkpoint is resumable."""
    from backend.services.workflow import WorkflowService
    from backend.models.workflow import WorkflowStage
    import json

    stage_repo = AsyncMock()
    stage1 = MagicMock(spec=WorkflowStage)
    stage1.status = "completed"
    stage1.checkpoint_data = json.dumps({"foo": "bar"})
    stage2 = MagicMock(spec=WorkflowStage)
    stage2.status = "failed"
    stage2.checkpoint_data = None
    stage_repo.list_by_run = AsyncMock(return_value=[stage1, stage2])

    service = WorkflowService(
        workflow_repository=AsyncMock(),
        run_repository=AsyncMock(),
        stage_repository=stage_repo,
        document_repository=AsyncMock(),
        storage=AsyncMock(),
    )

    run = MagicMock(spec=WorkflowRun)
    run.id = uuid4()
    run.status = "failed"

    assert await service.is_run_resumable(run) is True


@pytest.mark.asyncio
async def test_is_run_resumable_completed_is_false():
    """Completed run is never resumable (must replay instead)."""
    from backend.services.workflow import WorkflowService
    from backend.models.workflow import WorkflowStage
    import json

    stage_repo = AsyncMock()
    stage = MagicMock(spec=WorkflowStage)
    stage.status = "completed"
    stage.checkpoint_data = json.dumps({"foo": "bar"})
    stage_repo.list_by_run = AsyncMock(return_value=[stage])

    service = WorkflowService(
        workflow_repository=AsyncMock(),
        run_repository=AsyncMock(),
        stage_repository=stage_repo,
        document_repository=AsyncMock(),
        storage=AsyncMock(),
    )

    run = MagicMock(spec=WorkflowRun)
    run.id = uuid4()
    run.status = "completed"

    assert await service.is_run_resumable(run) is False


@pytest.mark.asyncio
async def test_is_run_resumable_no_checkpoint_is_false():
    """Run that failed before any checkpoint was written is not resumable."""
    from backend.services.workflow import WorkflowService
    from backend.models.workflow import WorkflowStage

    stage_repo = AsyncMock()
    stage = MagicMock(spec=WorkflowStage)
    stage.status = "failed"
    stage.checkpoint_data = None
    stage_repo.list_by_run = AsyncMock(return_value=[stage])

    service = WorkflowService(
        workflow_repository=AsyncMock(),
        run_repository=AsyncMock(),
        stage_repository=stage_repo,
        document_repository=AsyncMock(),
        storage=AsyncMock(),
    )

    run = MagicMock(spec=WorkflowRun)
    run.id = uuid4()
    run.status = "failed"

    assert await service.is_run_resumable(run) is False



