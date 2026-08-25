"""
Integration tests for workflow decision execution.

Tests that decisions actually change workflow execution paths, not just metadata.
"""

import pytest
import asyncio
from uuid import uuid4
from datetime import datetime, timezone

from backend.core.workflow.runner import WorkflowRunner, WorkflowEscalatedException, WorkflowBlockedException
from backend.core.workflow.stage import StageNode
from backend.core.workflow.decisions import DecisionEngine, WorkflowDecision
from backend.repositories.workflow import WorkflowStageRepository, WorkflowRunRepository
from pydantic import BaseModel


class TestWorkflowState(BaseModel):
    """Test workflow state."""
    workflow_run_id: str
    value: int = 0
    stage_count: int = 0


class CounterStage(StageNode[TestWorkflowState]):
    """Test stage that increments counter."""
    def __init__(self, name: str):
        super().__init__(name)

    async def execute(self, state: TestWorkflowState) -> dict:
        return {
            "value": state.value + 1,
            "stage_count": state.stage_count + 1
        }


class EmptyResultStage(StageNode[TestWorkflowState]):
    """Test stage that returns empty results."""
    def __init__(self, name: str):
        super().__init__(name)

    async def execute(self, state: TestWorkflowState) -> dict:
        return {"results_count": 0}


class FailingStage(StageNode[TestWorkflowState]):
    """Test stage that fails."""
    def __init__(self, name: str, retryable: bool = True):
        super().__init__(name)
        self.retryable = retryable
        self.attempt_count = 0

    async def execute(self, state: TestWorkflowState) -> dict:
        self.attempt_count += 1
        if self.retryable:
            raise TimeoutError("Transient failure")
        else:
            raise ValueError("Permanent failure")


class QualityGateStage(StageNode[TestWorkflowState]):
    """Test stage that blocks on quality gate."""
    def __init__(self, name: str, has_contradiction: bool = False):
        super().__init__(name)
        self.has_contradiction = has_contradiction

    async def execute(self, state: TestWorkflowState) -> dict:
        if self.has_contradiction:
            return {
                "quality_gate_blocked": True,
                "blocking_reason": "Contradiction detected: test mismatch"
            }
        else:
            return {
                "quality_gate_blocked": True,
                "blocking_reason": "Low confidence"
            }


class MockStageRepository:
    """Mock stage repository for testing."""
    def __init__(self):
        self.stages = {}
        self.all_decisions = []  # Track all decisions made

    async def create(self, **kwargs):
        stage_id = uuid4()
        stage = type('MockStage', (), {
            'id': stage_id,
            'retry_count': 0,
            **kwargs
        })()
        self.stages[stage_id] = stage
        return stage

    async def update(self, stage_id, **kwargs):
        if stage_id in self.stages:
            for key, value in kwargs.items():
                setattr(self.stages[stage_id], key, value)
            # Track decisions
            if 'decision_type' in kwargs:
                stage = self.stages[stage_id]
                self.all_decisions.append((
                    getattr(stage, 'stage_name', 'unknown'),
                    kwargs['decision_type'],
                    kwargs.get('decision_reason', '')
                ))
        return self.stages.get(stage_id)

    async def get_by_run_and_name(self, run_id, stage_name):
        for stage in self.stages.values():
            if hasattr(stage, 'run_id') and hasattr(stage, 'stage_name'):
                if stage.run_id == run_id and stage.stage_name == stage_name:
                    return stage
        return None

    async def list_by_run(self, run_id):
        return [s for s in self.stages.values() if hasattr(s, 'run_id') and s.run_id == run_id]

    def get_decisions(self):
        """Get all decisions made."""
        return self.all_decisions


class MockRunRepository:
    """Mock run repository for testing."""
    def __init__(self):
        self.runs = {}

    async def update(self, run_id, **kwargs):
        if run_id not in self.runs:
            self.runs[run_id] = {}
        self.runs[run_id].update(kwargs)


@pytest.mark.asyncio
async def test_continue_decision_executes_all_stages():
    """Test that CONTINUE decision allows all stages to execute."""
    stage_repo = MockStageRepository()
    run_repo = MockRunRepository()

    stages = [
        CounterStage("stage1"),
        CounterStage("stage2"),
        CounterStage("stage3"),
    ]

    edges = [
        ("stage1", "stage2"),
        ("stage2", "stage3"),
        ("stage3", "END"),
    ]

    runner = WorkflowRunner(
        workflow_name="test_continue",
        stages=stages,
        edges=edges,
        state_schema=TestWorkflowState,
        stage_repository=stage_repo
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "value": 0,
        "stage_count": 0
    }

    final_state = await runner.run(initial_state, run_repo)

    # All 3 stages should have executed
    assert final_state["stage_count"] == 3
    assert final_state["value"] == 3

    # Check decisions were CONTINUE
    decisions = stage_repo.get_decisions()
    assert len(decisions) == 3
    assert all(d[1] == "continue" for d in decisions)


@pytest.mark.asyncio
async def test_skip_decision_bypasses_stage():
    """Test that SKIP decision prevents stage execution from affecting state."""
    stage_repo = MockStageRepository()
    run_repo = MockRunRepository()

    stages = [
        CounterStage("stage1"),
        EmptyResultStage("stage2"),  # Will be skipped
        CounterStage("stage3"),
    ]

    edges = [
        ("stage1", "stage2"),
        ("stage2", "stage3"),
        ("stage3", "END"),
    ]

    runner = WorkflowRunner(
        workflow_name="test_skip",
        stages=stages,
        edges=edges,
        state_schema=TestWorkflowState,
        stage_repository=stage_repo
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "value": 0,
        "stage_count": 0
    }

    final_state = await runner.run(initial_state, run_repo)

    # Only 2 stages should have affected state (stage2 skipped)
    assert final_state["stage_count"] == 2
    assert final_state["value"] == 2

    # Check that stage2 was skipped
    decisions = stage_repo.get_decisions()
    assert decisions[1][1] == "skip"  # stage2
    assert decisions[1][2] and "no actionable" in decisions[1][2].lower()


@pytest.mark.asyncio
async def test_retry_decision_retries_stage():
    """Test that RETRY decision causes stage to retry with backoff."""
    stage_repo = MockStageRepository()
    run_repo = MockRunRepository()

    failing_stage = FailingStage("failing_stage", retryable=True)

    stages = [
        CounterStage("stage1"),
        failing_stage,
        CounterStage("stage3"),
    ]

    edges = [
        ("stage1", "failing_stage"),
        ("failing_stage", "stage3"),
        ("stage3", "END"),
    ]

    runner = WorkflowRunner(
        workflow_name="test_retry",
        stages=stages,
        edges=edges,
        state_schema=TestWorkflowState,
        stage_repository=stage_repo
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "value": 0,
        "stage_count": 0
    }

    # Should fail after max retries
    with pytest.raises(WorkflowBlockedException) as exc_info:
        await runner.run(initial_state, run_repo)

    assert "permanent failure" in str(exc_info.value).lower()

    # Check that stage was retried multiple times
    assert failing_stage.attempt_count > 1
    assert failing_stage.attempt_count <= 4  # Initial + 3 retries

    # Check decisions
    decisions = stage_repo.get_decisions()
    retry_decisions = [d for d in decisions if d[1] and "retry" in d[1]]
    block_decisions = [d for d in decisions if d[1] and "block" in d[1]]

    # Should have multiple retry decisions and one final block
    assert len(retry_decisions) >= 3, f"Expected >= 3 retry decisions, got {len(retry_decisions)}"
    assert len(block_decisions) == 1, f"Expected 1 block decision, got {len(block_decisions)}"


@pytest.mark.asyncio
async def test_escalate_decision_pauses_workflow():
    """Test that ESCALATE decision pauses workflow for human intervention."""
    stage_repo = MockStageRepository()
    run_repo = MockRunRepository()

    stages = [
        CounterStage("stage1"),
        QualityGateStage("quality_gate", has_contradiction=True),
        CounterStage("stage3"),
    ]

    edges = [
        ("stage1", "quality_gate"),
        ("quality_gate", "stage3"),
        ("stage3", "END"),
    ]

    runner = WorkflowRunner(
        workflow_name="test_escalate",
        stages=stages,
        edges=edges,
        state_schema=TestWorkflowState,
        stage_repository=stage_repo
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "value": 0,
        "stage_count": 0
    }

    # Should escalate instead of failing
    final_state = await runner.run(initial_state, run_repo)

    # Workflow should pause (status=escalated in state)
    assert final_state.get("status") == "escalated", f"Expected escalated, got {final_state.get('status')}"
    assert "contradiction" in final_state.get("reason", "").lower(), f"Expected contradiction in reason, got {final_state.get('reason')}"

    # Check decision was made
    decisions = stage_repo.get_decisions()
    escalate_decision = [d for d in decisions if d[1] == "escalate"]
    assert len(escalate_decision) >= 1, f"Expected at least 1 escalate decision, got {len(escalate_decision)}: {decisions}"
    assert "contradiction" in escalate_decision[0][2].lower()


@pytest.mark.asyncio
async def test_block_decision_stops_workflow():
    """Test that BLOCK decision permanently stops workflow."""
    stage_repo = MockStageRepository()
    run_repo = MockRunRepository()

    stages = [
        CounterStage("stage1"),
        FailingStage("failing_stage", retryable=False),  # Non-retryable
        CounterStage("stage3"),
    ]

    edges = [
        ("stage1", "failing_stage"),
        ("failing_stage", "stage3"),
        ("stage3", "END"),
    ]

    runner = WorkflowRunner(
        workflow_name="test_block",
        stages=stages,
        edges=edges,
        state_schema=TestWorkflowState,
        stage_repository=stage_repo
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "value": 0,
        "stage_count": 0
    }

    # Should block immediately
    with pytest.raises(WorkflowBlockedException) as exc_info:
        await runner.run(initial_state, run_repo)

    assert "permanent failure" in str(exc_info.value).lower()

    # Check decision
    decisions = stage_repo.get_decisions()
    block_decision = [d for d in decisions if d[1] == "block"]
    assert len(block_decision) == 1


@pytest.mark.asyncio
async def test_decision_persists_to_database():
    """Test that decisions are persisted with reason and metadata."""
    stage_repo = MockStageRepository()
    run_repo = MockRunRepository()

    stages = [
        EmptyResultStage("skip_stage"),
        CounterStage("continue_stage"),
    ]

    edges = [
        ("skip_stage", "continue_stage"),
        ("continue_stage", "END"),
    ]

    runner = WorkflowRunner(
        workflow_name="test_persistence",
        stages=stages,
        edges=edges,
        state_schema=TestWorkflowState,
        stage_repository=stage_repo
    )

    initial_state = {
        "workflow_run_id": str(uuid4()),
        "value": 0,
        "stage_count": 0
    }

    await runner.run(initial_state, run_repo)

    # Check all stages have decisions
    for stage in stage_repo.stages.values():
        assert hasattr(stage, 'decision_type')
        assert hasattr(stage, 'decision_reason')
        assert hasattr(stage, 'decision_metadata')
        assert stage.decision_type in [d.value for d in WorkflowDecision]
        assert stage.decision_reason is not None
        assert stage.decision_metadata is not None
