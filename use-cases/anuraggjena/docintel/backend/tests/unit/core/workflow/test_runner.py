import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any
from uuid import uuid4

from backend.core.workflow.runner import WorkflowRunner, WorkflowBlockedException
from backend.core.workflow.stage import StageNode
from backend.tests.unit.core.workflow.test_stage import TestState, TestStage


@pytest.fixture
def mock_run_repository():
    """Mock workflow run repository"""
    repo = AsyncMock()
    repo.update = AsyncMock()
    return repo


@pytest.fixture
def mock_stage_repository():
    """Mock workflow stage repository"""
    repo = AsyncMock()

    # Mock stage record
    mock_stage = MagicMock()
    mock_stage.id = uuid4()
    mock_stage.retry_count = 0

    repo.get_by_run_and_name = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=mock_stage)
    repo.update = AsyncMock()
    repo.list_by_run = AsyncMock(return_value=[])
    return repo


@pytest.mark.asyncio
async def test_workflow_runner_single_stage(mock_run_repository, mock_stage_repository):
    """Test workflow with single stage"""
    stage = TestStage("stage1")

    runner = WorkflowRunner(
        workflow_name="test_workflow",
        stages=[stage],
        edges=[("stage1", "END")],
        state_schema=TestState,
        stage_repository=mock_stage_repository
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": "ws-1",
        "document_id": "doc-1",
        "counter": 0
    }

    final_state = await runner.run(initial_state, mock_run_repository)

    assert final_state["counter"] == 1
    assert mock_run_repository.update.called
    assert mock_stage_repository.create.called


@pytest.mark.asyncio
async def test_workflow_runner_multiple_stages(mock_run_repository, mock_stage_repository):
    """Test workflow with multiple stages"""
    stage1 = TestStage("stage1")
    stage2 = TestStage("stage2")

    runner = WorkflowRunner(
        workflow_name="multi_stage_workflow",
        stages=[stage1, stage2],
        edges=[("stage1", "stage2"), ("stage2", "END")],
        state_schema=TestState,
        stage_repository=mock_stage_repository
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": "ws-1",
        "document_id": "doc-1",
        "counter": 0
    }

    final_state = await runner.run(initial_state, mock_run_repository)

    assert final_state["counter"] == 2  # Each stage increments
    assert final_state["message"] == "Processed by stage2"


@pytest.mark.asyncio
async def test_workflow_runner_error_handling(mock_run_repository, mock_stage_repository):
    """Test workflow error handling"""

    class FailingStage(StageNode[TestState]):
        async def execute(self, state: TestState) -> Dict[str, Any]:
            raise RuntimeError("Stage execution failed")

    stage = FailingStage("failing_stage")

    runner = WorkflowRunner(
        workflow_name="failing_workflow",
        stages=[stage],
        edges=[("failing_stage", "END")],
        state_schema=TestState,
        stage_repository=mock_stage_repository
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": "ws-1",
        "document_id": "doc-1"
    }

    with pytest.raises(WorkflowBlockedException):
        await runner.run(initial_state, mock_run_repository)

    # Verify status updated to failed
    assert mock_run_repository.update.called


@pytest.mark.asyncio
async def test_workflow_runner_retry_success_clears_stale_error_message(mock_run_repository, mock_stage_repository):
    """FIX 3: Verify that when a stage fails transiently and succeeds on retry, error_message is cleared."""
    attempts = [0]

    class TransientFailingStage(StageNode[TestState]):
        async def execute(self, state: TestState) -> Dict[str, Any]:
            attempts[0] += 1
            if attempts[0] == 1:
                raise TimeoutError("Temporary timeout on remote API")
            return {"counter": 42, "status": "ok"}

    stage = TransientFailingStage("transient_stage")
    runner = WorkflowRunner(
        workflow_name="retry_workflow",
        stages=[stage],
        edges=[("transient_stage", "END")],
        state_schema=TestState,
        stage_repository=mock_stage_repository
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": "ws-1",
        "document_id": "doc-1",
        "counter": 0
    }

    final_state = await runner.run(initial_state, mock_run_repository)
    assert final_state["counter"] == 42
    assert attempts[0] == 2

    # Verify that the final update calls had error_message=None
    final_stage_updates = [call.kwargs for call in mock_stage_repository.update.call_args_list if "status" in call.kwargs]
    # Check that the last update marked status as completed and error_message is None
    completed_updates = [u for u in final_stage_updates if u.get("status") == "completed"]
    assert len(completed_updates) > 0
    assert completed_updates[-1].get("error_message") is None

