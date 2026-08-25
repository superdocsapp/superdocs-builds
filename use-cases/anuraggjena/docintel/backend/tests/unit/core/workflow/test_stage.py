import pytest
from typing import Dict, Any
from pydantic import BaseModel, ConfigDict

from backend.core.workflow.stage import StageNode, WorkflowState


class TestState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workflow_run_id: str
    workspace_id: str
    document_id: str
    counter: int = 0
    message: str = ""


class TestStage(StageNode[TestState]):
    """Test stage implementation"""

    async def execute(self, state: TestState) -> Dict[str, Any]:
        return {
            "counter": state.counter + 1,
            "message": f"Processed by {self.name}"
        }


@pytest.mark.asyncio
async def test_stage_execute():
    """Test stage execution returns state updates"""
    stage = TestStage("test_stage")

    state = TestState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1",
        counter=5
    )

    updates = await stage.execute(state)

    assert updates["counter"] == 6
    assert updates["message"] == "Processed by test_stage"


@pytest.mark.asyncio
async def test_stage_call_wraps_execute():
    """Test __call__ wraps execute with logging"""
    stage = TestStage("test_stage")

    state = TestState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1"
    )

    updates = await stage(state)

    assert updates["counter"] == 1
    assert "message" in updates


@pytest.mark.asyncio
async def test_stage_error_handling():
    """Test stage error handling and logging"""

    class FailingStage(StageNode[TestState]):
        async def execute(self, state: TestState) -> Dict[str, Any]:
            raise ValueError("Stage failed")

    stage = FailingStage("failing_stage")
    state = TestState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1"
    )

    with pytest.raises(ValueError, match="Stage failed"):
        await stage(state)


def test_workflow_state_initialization():
    """Test WorkflowState base class"""
    state = WorkflowState(
        workflow_run_id="run-1",
        workspace_id="ws-1",
        document_id="doc-1"
    )

    assert state.status == "pending"
    assert state.current_stage is None
    assert state.error is None
