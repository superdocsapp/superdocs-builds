import pytest
import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

from backend.core.workflow.task_manager import TaskManager
from backend.core.workflow.registry import WorkflowRegistry
from backend.tests.unit.core.workflow.test_stage import TestState, TestStage


@pytest.fixture
def workflow_registry_with_test():
    """Registry with test workflow registered"""
    registry = WorkflowRegistry()
    stage = TestStage("stage1")

    registry.register(
        workflow_name="test_workflow",
        stages=[stage],
        edges=[("stage1", "END")],
        state_schema=TestState
    )

    return registry


@pytest.fixture
def mock_repositories():
    """Mock repositories for task manager"""
    run_repo = AsyncMock()
    stage_repo = AsyncMock()
    stage_repo.get_by_run_and_name = AsyncMock(return_value=None)
    stage_repo.create = AsyncMock()
    stage_repo.update = AsyncMock()
    return run_repo, stage_repo


@pytest.mark.asyncio
async def test_start_workflow(workflow_registry_with_test, mock_repositories):
    """Test starting a workflow task"""
    run_repo, stage_repo = mock_repositories

    task_manager = TaskManager(run_repo, stage_repo)

    run_id = uuid4()
    initial_state = {
        "workflow_run_id": str(run_id),
        "workspace_id": "ws-1",
        "document_id": "doc-1"
    }

    # Inject test registry
    from backend.core.workflow import task_manager as tm_module
    original_registry = tm_module.workflow_registry
    tm_module.workflow_registry = workflow_registry_with_test

    try:
        # Start workflow in background
        await task_manager.start_workflow(run_id, "test_workflow", initial_state)

        # Wait for task to finish
        task = task_manager._running_tasks.get(str(run_id))
        if task:
            try:
                await asyncio.wait_for(task, timeout=5.0)
            except Exception:
                pass

        # Verify workflow completed (task removed from running tasks)
        assert not task_manager.is_running(run_id)
        assert task_manager.get_running_count() == 0
    finally:
        tm_module.workflow_registry = original_registry


@pytest.mark.asyncio
async def test_cancel_workflow(mock_repositories):
    """Test cancelling a running workflow"""
    run_repo, stage_repo = mock_repositories

    task_manager = TaskManager(run_repo, stage_repo)

    run_id = uuid4()

    # Create a long-running mock task
    async def mock_workflow():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            # Expected when cancelled
            raise

    task = asyncio.create_task(mock_workflow())
    task_manager._running_tasks[str(run_id)] = task

    # Task is running before cancel
    assert task_manager.is_running(run_id)

    result = await task_manager.cancel_workflow(run_id)

    assert result is True
    # Give time for cancellation to propagate
    await asyncio.sleep(0.1)
    # Task should be cancelled
    assert task.cancelled()


@pytest.mark.asyncio
async def test_get_running_count(mock_repositories):
    """Test getting count of running workflows"""
    run_repo, stage_repo = mock_repositories

    task_manager = TaskManager(run_repo, stage_repo)

    assert task_manager.get_running_count() == 0

    # Simulate running task
    async def dummy():
        await asyncio.sleep(0.1)

    task_manager._running_tasks["run-1"] = asyncio.create_task(dummy())
    task_manager._running_tasks["run-2"] = asyncio.create_task(dummy())

    assert task_manager.get_running_count() == 2


@pytest.mark.asyncio
async def test_get_running_ids(mock_repositories):
    """Test getting list of running workflow IDs"""
    run_repo, stage_repo = mock_repositories

    task_manager = TaskManager(run_repo, stage_repo)

    assert task_manager.get_running_ids() == []

    # Simulate running tasks
    async def dummy():
        await asyncio.sleep(0.1)

    task_manager._running_tasks["run-1"] = asyncio.create_task(dummy())
    task_manager._running_tasks["run-2"] = asyncio.create_task(dummy())

    running_ids = task_manager.get_running_ids()
    assert len(running_ids) == 2
    assert "run-1" in running_ids
    assert "run-2" in running_ids

    # Clean up tasks
    for task in task_manager._running_tasks.values():
        task.cancel()
    await asyncio.sleep(0.01)
