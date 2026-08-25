"""
Focused tests for WorkflowRunner resume idempotency.

Requirements verified:
1. A completed stage is skipped (not re-executed) on resume.
2. superdocs_instruction is never re-called if already completed.
3. superdocs_approval resumes and applies the approval exactly once.
4. The workflow continues through to superdocs_export after resume.
5. A fresh (first) run still executes superdocs_instruction normally.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from backend.core.workflow.runner import WorkflowRunner, WorkflowEscalatedException
from backend.core.workflow.stage import StageNode
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class SimpleState(BaseModel):
    workflow_run_id: str = ""
    step_a_done: bool = False
    step_b_done: bool = False
    step_c_done: bool = False


def _make_stage_record(name, status, checkpoint=None):
    rec = MagicMock()
    rec.id = uuid4()
    rec.stage_name = name
    rec.status = status
    rec.retry_count = 0
    rec.checkpoint_data = json.dumps(checkpoint) if checkpoint else None
    return rec


def _make_stage_repo(records_by_name: dict):
    """
    Returns a mock WorkflowStageRepository.
    records_by_name: {stage_name: record_or_None}
    """
    repo = AsyncMock()

    async def get_by_run_and_name(run_id, stage_name):
        return records_by_name.get(stage_name)

    repo.get_by_run_and_name = AsyncMock(side_effect=get_by_run_and_name)
    repo.create = AsyncMock(side_effect=lambda **kw: _make_stage_record(kw["stage_name"], "running"))
    repo.update = AsyncMock(side_effect=lambda id, **kw: _make_stage_record("?", kw.get("status","running")))
    repo.list_by_run = AsyncMock(return_value=list(records_by_name.values()))
    return repo


def _make_run_repo():
    repo = AsyncMock()
    repo.update = AsyncMock()
    return repo


def _make_runner(stages, stage_repo):
    edges = [(stages[i].name, stages[i+1].name) for i in range(len(stages)-1)]
    edges.append((stages[-1].name, "END"))
    return WorkflowRunner(
        workflow_name="test_wf",
        stages=stages,
        edges=edges,
        state_schema=SimpleState,
        stage_repository=stage_repo,
    )


class _SimpleStage(StageNode):
    def __init__(self, name, return_key, execute_mock=None):
        super().__init__(name)
        self._return_key = return_key
        self._execute_mock = execute_mock or AsyncMock(return_value={return_key: True})

    async def execute(self, state):
        return await self._execute_mock(state)


# ---------------------------------------------------------------------------
# TEST 1: completed stage is skipped on resume — execute is NOT called again
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completed_stage_is_skipped_on_resume():
    """
    If stage_a already has status=completed in the DB, its execute() must
    NOT be called when the workflow re-runs (as happens on resume).
    """
    run_id = str(uuid4())
    execute_a = AsyncMock(return_value={"step_a_done": True})
    execute_b = AsyncMock(return_value={"step_b_done": True})

    stage_a = _SimpleStage("stage_a", "step_a_done", execute_a)
    stage_b = _SimpleStage("stage_b", "step_b_done", execute_b)

    # stage_a already completed with checkpoint
    completed_checkpoint = {"workflow_run_id": run_id, "step_a_done": True}
    completed_rec = _make_stage_record("stage_a", "completed", completed_checkpoint)
    stage_repo = _make_stage_repo({"stage_a": completed_rec, "stage_b": None})

    runner = _make_runner([stage_a, stage_b], stage_repo)
    run_repo = _make_run_repo()

    await runner.run({"workflow_run_id": run_id}, run_repo)

    # stage_a must NOT have been executed
    execute_a.assert_not_called()
    # stage_b must have been executed once
    execute_b.assert_called_once()


# ---------------------------------------------------------------------------
# TEST 2: superdocs_instruction skipped on resume; superdocs_approval runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_superdocs_instruction_skipped_approval_runs_on_resume():
    """
    Simulates the exact resume scenario: superdocs_instruction is completed,
    superdocs_approval is the stage that needs to re-run (HITL path).
    superdocs_instruction.execute() must never be called again.
    """
    run_id = str(uuid4())
    instruction_execute = AsyncMock(return_value={"step_a_done": True, "superdocs_job_id": "job-123"})
    approval_execute = AsyncMock(return_value={"step_b_done": True})

    instruction_stage = _SimpleStage("superdocs_instruction", "step_a_done", instruction_execute)
    approval_stage = _SimpleStage("superdocs_approval", "step_b_done", approval_execute)

    instruction_checkpoint = {
        "workflow_run_id": run_id,
        "step_a_done": True,
        "superdocs_job_id": "job-123",
    }
    instruction_rec = _make_stage_record("superdocs_instruction", "completed", instruction_checkpoint)
    # superdocs_approval has no record yet (re-runs fresh on resume)
    stage_repo = _make_stage_repo({
        "superdocs_instruction": instruction_rec,
        "superdocs_approval": None,
    })

    runner = _make_runner([instruction_stage, approval_stage], stage_repo)
    run_repo = _make_run_repo()

    await runner.run({"workflow_run_id": run_id}, run_repo)

    instruction_execute.assert_not_called()
    approval_execute.assert_called_once()


# ---------------------------------------------------------------------------
# TEST 3: approved claim applied exactly once — approval stage not double-called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approval_stage_not_double_executed_if_already_completed():
    """
    If superdocs_approval itself completed (all claims approved, SuperDocs
    notified), it must not re-execute on a second resume attempt.
    This prevents double-sending approve_change to SuperDocs.
    """
    run_id = str(uuid4())
    approval_execute = AsyncMock(return_value={"step_b_done": True, "approved_count": 1})
    export_execute = AsyncMock(return_value={"step_c_done": True})

    approval_stage = _SimpleStage("superdocs_approval", "step_b_done", approval_execute)
    export_stage = _SimpleStage("superdocs_export", "step_c_done", export_execute)

    approval_checkpoint = {
        "workflow_run_id": run_id,
        "step_b_done": True,
        "approved_count": 1,
    }
    approval_rec = _make_stage_record("superdocs_approval", "completed", approval_checkpoint)

    stage_repo = _make_stage_repo({
        "superdocs_approval": approval_rec,
        "superdocs_export": None,
    })

    runner = _make_runner([approval_stage, export_stage], stage_repo)
    run_repo = _make_run_repo()

    await runner.run({"workflow_run_id": run_id}, run_repo)

    # Approval must NOT re-execute (would double-send to SuperDocs)
    approval_execute.assert_not_called()
    # Export must execute normally
    export_execute.assert_called_once()


# ---------------------------------------------------------------------------
# TEST 4: workflow continues to superdocs_export after resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workflow_continues_to_export_after_resume():
    """
    Full resume path: instruction done, approval re-runs and completes,
    export runs. Verifies the workflow reaches the final stage.
    """
    run_id = str(uuid4())
    instruction_execute = AsyncMock(return_value={"step_a_done": True})
    approval_execute = AsyncMock(return_value={"step_b_done": True, "approved_count": 1})
    export_execute = AsyncMock(return_value={"step_c_done": True, "docx_url": "https://example.com/export.docx"})

    instruction_stage = _SimpleStage("superdocs_instruction", "step_a_done", instruction_execute)
    approval_stage = _SimpleStage("superdocs_approval", "step_b_done", approval_execute)
    export_stage = _SimpleStage("superdocs_export", "step_c_done", export_execute)

    instruction_checkpoint = {"workflow_run_id": run_id, "step_a_done": True}
    instruction_rec = _make_stage_record("superdocs_instruction", "completed", instruction_checkpoint)

    stage_repo = _make_stage_repo({
        "superdocs_instruction": instruction_rec,
        "superdocs_approval": None,
        "superdocs_export": None,
    })

    runner = _make_runner([instruction_stage, approval_stage, export_stage], stage_repo)
    run_repo = _make_run_repo()

    await runner.run({"workflow_run_id": run_id}, run_repo)

    instruction_execute.assert_not_called()
    approval_execute.assert_called_once()
    export_execute.assert_called_once()


# ---------------------------------------------------------------------------
# TEST 5: fresh run (no prior records) still executes all stages normally
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_run_executes_all_stages():
    """
    On a first (fresh) run with no prior stage records, ALL stages must
    execute normally — no stages skipped.
    """
    run_id = str(uuid4())
    execute_a = AsyncMock(return_value={"step_a_done": True})
    execute_b = AsyncMock(return_value={"step_b_done": True})
    execute_c = AsyncMock(return_value={"step_c_done": True})

    stage_a = _SimpleStage("superdocs_instruction", "step_a_done", execute_a)
    stage_b = _SimpleStage("superdocs_approval", "step_b_done", execute_b)
    stage_c = _SimpleStage("superdocs_export", "step_c_done", execute_c)

    # No prior records for any stage
    stage_repo = _make_stage_repo({
        "superdocs_instruction": None,
        "superdocs_approval": None,
        "superdocs_export": None,
    })

    runner = _make_runner([stage_a, stage_b, stage_c], stage_repo)
    run_repo = _make_run_repo()

    await runner.run({"workflow_run_id": run_id}, run_repo)

    execute_a.assert_called_once()
    execute_b.assert_called_once()
    execute_c.assert_called_once()


# ---------------------------------------------------------------------------
# TEST 6: cancelled run with checkpoint resumes from first unfinished stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancelled_run_with_checkpoint_resumes_from_unfinished_stage():
    """
    If a workflow was cancelled while stage_b was running after stage_a completed:
    Calling runner.resume() must skip stage_a and execute stage_b and stage_c.
    """
    run_id = uuid4()
    execute_a = AsyncMock(return_value={"step_a_done": True})
    execute_b = AsyncMock(return_value={"step_b_done": True})
    execute_c = AsyncMock(return_value={"step_c_done": True})

    stage_a = _SimpleStage("stage_a", "step_a_done", execute_a)
    stage_b = _SimpleStage("stage_b", "step_b_done", execute_b)
    stage_c = _SimpleStage("stage_c", "step_c_done", execute_c)

    # stage_a is completed with checkpoint, stage_b was cancelled
    stage_a_rec = _make_stage_record("stage_a", "completed", {"workflow_run_id": str(run_id), "step_a_done": True})
    stage_b_rec = _make_stage_record("stage_b", "cancelled", None)

    stage_repo = _make_stage_repo({
        "stage_a": stage_a_rec,
        "stage_b": stage_b_rec,
        "stage_c": None,
    })

    runner = _make_runner([stage_a, stage_b, stage_c], stage_repo)
    run_repo = _make_run_repo()

    final_state = await runner.resume(run_id, run_repo)

    # stage_a was not re-executed
    execute_a.assert_not_called()
    # stage_b and stage_c executed
    execute_b.assert_called_once()
    execute_c.assert_called_once()
    assert final_state.get("step_a_done") is True
    assert final_state.get("step_b_done") is True
    assert final_state.get("step_c_done") is True


# ---------------------------------------------------------------------------
# TEST 7: interrupted/failed run with checkpoint resumes from unfinished stage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interrupted_run_with_checkpoint_resumes_from_unfinished_stage():
    """
    If a workflow failed/interrupted on stage_b after stage_a completed:
    Calling runner.resume() must skip stage_a and continue execution from stage_b.
    """
    run_id = uuid4()
    execute_a = AsyncMock(return_value={"step_a_done": True})
    execute_b = AsyncMock(return_value={"step_b_done": True})
    execute_c = AsyncMock(return_value={"step_c_done": True})

    stage_a = _SimpleStage("stage_a", "step_a_done", execute_a)
    stage_b = _SimpleStage("stage_b", "step_b_done", execute_b)
    stage_c = _SimpleStage("stage_c", "step_c_done", execute_c)

    stage_a_rec = _make_stage_record("stage_a", "completed", {"workflow_run_id": str(run_id), "step_a_done": True})
    stage_b_rec = _make_stage_record("stage_b", "failed", None)

    stage_repo = _make_stage_repo({
        "stage_a": stage_a_rec,
        "stage_b": stage_b_rec,
        "stage_c": None,
    })

    runner = _make_runner([stage_a, stage_b, stage_c], stage_repo)
    run_repo = _make_run_repo()

    final_state = await runner.resume(run_id, run_repo)

    execute_a.assert_not_called()
    execute_b.assert_called_once()
    execute_c.assert_called_once()
    assert final_state.get("step_a_done") is True
    assert final_state.get("step_b_done") is True
    assert final_state.get("step_c_done") is True

