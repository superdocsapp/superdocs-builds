"""
E2E tests for quality gate blocking behavior.

Tests verify:
- Gate passes when all checks pass
- Gate raises ValueError when blocking check fails + block_on_failure=True
- Gate does NOT raise when block_on_failure=False even with blocking failure
- WorkflowRunner marks stage as failed and re-raises when gate blocks
- Gate result is persisted before the raise

WorkflowRunner.__init__ signature:
    workflow_name, stages, edges, state_schema, stage_repository

WorkflowRunner.run() signature:
    initial_state, run_repository
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from typing import TypedDict, Optional

from backend.core.quality_gate.stage import QualityGateStage
from backend.core.quality_gate.checks import BaseCheck, CheckSeverity, CheckStatus
from backend.core.workflow.runner import WorkflowRunner, WorkflowBlockedException
from backend.core.workflow.stage import StageNode


# ---------------------------------------------------------------------------
# Minimal test state schema — TypedDict so LangGraph passes state as a dict,
# which is required by QualityGateStage.execute() that uses state.get().
# ---------------------------------------------------------------------------

class QGTestState(TypedDict, total=False):
    workflow_run_id: str
    workspace_id: str
    document_id: str
    claims: list
    status: str
    current_stage: Optional[str]
    error: Optional[str]
    quality_gate_status: Optional[str]
    quality_gate_blocking: Optional[bool]
    quality_gate_details: list


# ---------------------------------------------------------------------------
# Test check implementations
# ---------------------------------------------------------------------------

class AlwaysPassCheck(BaseCheck):
    name = "always_pass"
    severity = CheckSeverity.INFO
    blocking = False

    async def run(self, state, config):
        return self.passed("All good")


class AlwaysBlockCheck(BaseCheck):
    name = "always_block"
    severity = CheckSeverity.ERROR
    blocking = True

    async def run(self, state, config):
        return self.failed("Critical issue found", {"detail": "blocking failure"})


# ---------------------------------------------------------------------------
# Helper stages / factories
# ---------------------------------------------------------------------------

class DataStage(StageNode):
    """Populates claims so the downstream gate has something to check."""
    def __init__(self):
        super().__init__(name="data_stage")

    async def execute(self, state):
        return {"claims": [{"content": "claim 1"}, {"content": "claim 2"}]}


def _make_mock_config(*, block_on_failure: bool = True):
    mock_config = MagicMock()
    mock_config.enabled = True
    mock_config.block_on_failure = block_on_failure
    mock_config.checks_config = {}
    mock_config.id = str(uuid4())
    return mock_config


def _make_config_repo(*, block_on_failure: bool = True):
    mock_config = _make_mock_config(block_on_failure=block_on_failure)
    repo = AsyncMock()
    repo.get_by_workspace = AsyncMock(return_value=mock_config)
    return repo


def _make_result_repo():
    repo = AsyncMock()
    repo.create = AsyncMock(return_value=MagicMock())
    return repo


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


def _initial_state(**overrides):
    base = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests — QualityGateStage.execute() directly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quality_gate_passes_when_no_blocking_failures():
    """Gate with only passing checks returns passed status and does not raise."""
    gate = QualityGateStage(
        checks=[AlwaysPassCheck()],
        config_repository=_make_config_repo(),
        result_repository=_make_result_repo(),
    )

    state = _initial_state(claims=[{"content": "HS code 8471.30"}])
    result = await gate.execute(state)

    assert result["quality_gate_status"] == "passed"
    assert result["quality_gate_blocking"] is False


@pytest.mark.asyncio
async def test_quality_gate_raises_on_blocking_failure():
    """Gate with blocking failure + block_on_failure=True raises ValueError."""
    gate = QualityGateStage(
        checks=[AlwaysBlockCheck()],
        config_repository=_make_config_repo(block_on_failure=True),
        result_repository=_make_result_repo(),
    )

    state = _initial_state(claims=[{"content": "c1"}, {"content": "c2"}])

    with pytest.raises(ValueError, match="Quality gate blocked"):
        await gate.execute(state)


@pytest.mark.asyncio
async def test_quality_gate_does_not_block_when_flag_false():
    """Gate with blocking failure but block_on_failure=False does NOT raise."""
    gate = QualityGateStage(
        checks=[AlwaysBlockCheck()],
        config_repository=_make_config_repo(block_on_failure=False),
        result_repository=_make_result_repo(),
    )

    state = _initial_state(claims=[])
    result = await gate.execute(state)

    assert result["quality_gate_status"] == "failed"
    assert result["quality_gate_blocking"] is True


@pytest.mark.asyncio
async def test_quality_gate_persists_result_even_on_failure():
    """Gate result is saved to DB even when it subsequently raises ValueError."""
    result_repo = _make_result_repo()

    gate = QualityGateStage(
        checks=[AlwaysBlockCheck()],
        config_repository=_make_config_repo(block_on_failure=True),
        result_repository=result_repo,
    )

    state = _initial_state()

    with pytest.raises(ValueError):
        await gate.execute(state)

    # Result should have been persisted before the raise
    assert result_repo.create.called


# ---------------------------------------------------------------------------
# Tests — WorkflowRunner integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_quality_gate_in_workflow_blocks_run():
    """
    When quality gate is embedded in a workflow and blocks, WorkflowRunner:
    - marks the gate stage as 'failed' in the stage repository
    - re-raises the ValueError
    """
    stage_repo = _make_stage_repo()
    run_repo = _make_run_repo()

    gate_stage = QualityGateStage(
        checks=[AlwaysBlockCheck()],
        config_repository=_make_config_repo(block_on_failure=True),
        result_repository=_make_result_repo(),
    )

    runner = WorkflowRunner(
        workflow_name="test_workflow",
        stages=[DataStage(), gate_stage],
        edges=[("data_stage", "quality_gate"), ("quality_gate", "END")],
        state_schema=QGTestState,
        stage_repository=stage_repo,
    )

    initial_state = _initial_state()

    with pytest.raises((ValueError, WorkflowBlockedException)):
        await runner.run(initial_state, run_repo)

    # Verify the quality_gate stage was marked as failed
    update_calls = stage_repo.update.call_args_list
    failed_updates = [
        c for c in update_calls
        if c.kwargs.get("status") == "failed" or (len(c.args) > 1 and c.args[1] == "failed")
    ]
    assert len(failed_updates) >= 1


@pytest.mark.asyncio
async def test_workflow_run_marked_failed_when_gate_blocks():
    """WorkflowRunner.run() updates the run record to 'blocked' or 'failed' on gate block."""
    run_repo = _make_run_repo()

    gate_stage = QualityGateStage(
        checks=[AlwaysBlockCheck()],
        config_repository=_make_config_repo(block_on_failure=True),
        result_repository=_make_result_repo(),
    )

    runner = WorkflowRunner(
        workflow_name="test_workflow",
        stages=[gate_stage],
        edges=[("quality_gate", "END")],
        state_schema=QGTestState,
        stage_repository=_make_stage_repo(),
    )

    initial_state = _initial_state()

    with pytest.raises((ValueError, WorkflowBlockedException)):
        await runner.run(initial_state, run_repo)

    # run_repository.update should have been called with status='blocked' or 'failed'
    update_calls = run_repo.update.call_args_list
    failed_run_updates = [
        c for c in update_calls
        if c.kwargs.get("status") in ("blocked", "failed")
    ]
    assert len(failed_run_updates) >= 1
