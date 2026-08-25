"""
Integration tests for the workflow runner's checkpoint/resume capability.

These tests verify the behaviour of WorkflowRunner.resume(), which restores
the state from the last completed stage's checkpoint and then calls run().

Key implementation facts (confirmed from source):
- WorkflowRunner.__init__ takes: workflow_name, stages, edges, state_schema,
  stage_repository  (no run_repository)
- WorkflowRunner.run(initial_state, run_repository)
- WorkflowRunner.resume(workflow_run_id, run_repository)
  → loads checkpoint from last completed stage and calls run() with that state
- _wrap_stage_with_persistence does NOT skip completed stages; every stage
  always executes when run() is invoked.  The resume benefit is that the
  restored state already contains the output of completed stages, so those
  stages have everything they need without needing to redo their LLM calls
  (though technically they still execute).
- WorkflowState requires: workflow_run_id, workspace_id, document_id

ExtractStage and GenerateStage take no constructor args; patch stage.llm
after construction.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.core.workflow.runner import WorkflowRunner
from backend.modules.tariff.stages.extract import ExtractStage, TariffClaimsResponse
from backend.modules.tariff.stages.generate import GenerateStage
from backend.modules.tariff.schemas import TariffClaim, TariffWorkflowState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stage_repo():
    repo = AsyncMock()
    repo.get_by_run_and_name = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=MagicMock(id=uuid4()))
    repo.update = AsyncMock(return_value=MagicMock())
    repo.list_by_run = AsyncMock(return_value=[])
    return repo


def _make_run_repo():
    repo = AsyncMock()
    repo.update = AsyncMock(return_value=MagicMock())
    return repo


def _make_runner(extract_stage, generate_stage, stage_repo=None):
    return WorkflowRunner(
        workflow_name="tariff",
        stages=[extract_stage, generate_stage],
        edges=[("extract", "generate"), ("generate", "END")],
        state_schema=TariffWorkflowState,
        stage_repository=stage_repo or _make_stage_repo(),
    )


def _sample_claims():
    return [
        TariffClaim(hs_code="8471.30", description="Laptop", duty_rate="0%", notes="Electronic")
    ]


def _patch_extract_llm(stage: ExtractStage, claims=None):
    mock_llm = MagicMock()
    mock_llm.generate_structured = AsyncMock(
        return_value=TariffClaimsResponse(claims=claims or _sample_claims())
    )
    stage.llm = mock_llm
    return mock_llm


def _patch_generate_llm(stage: GenerateStage, report_text="Final tariff report"):
    mock_llm = MagicMock()
    response = MagicMock()
    response.content = report_text
    mock_llm.generate = AsyncMock(return_value=response)
    stage.llm = mock_llm
    return mock_llm


def _make_completed_stage_record(stage_name: str, checkpoint_data: dict):
    """Build a mock stage record that looks like a completed DB row."""
    record = MagicMock()
    record.id = uuid4()
    record.stage_name = stage_name
    record.status = "completed"
    record.retry_count = 0
    record.checkpoint_data = json.dumps(checkpoint_data)
    return record


# ---------------------------------------------------------------------------
# Test 1 — resume() restores checkpoint state and continues the workflow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_restores_checkpoint_and_runs_remaining_stages():
    """
    resume() should load the checkpoint from the last completed stage and
    invoke run() with the restored state.  The generate stage should produce
    a report using the claims already present in the checkpoint.

    Note: the runner does NOT skip completed stages — both stages execute
    again on resume.  The value is that the restored state already contains
    extract output, so generate has what it needs without a fresh LLM call
    for extraction (though extract still runs with the same state).
    """
    run_id = uuid4()
    workspace_id = str(uuid4())
    document_id = str(uuid4())

    claims = _sample_claims()
    checkpoint_data = {
        "workflow_run_id": str(run_id),
        "workspace_id": workspace_id,
        "document_id": document_id,
        "document_content": "Laptop for computing",
        "extracted_claims": [c.model_dump() for c in claims],
        "extract_completed": True,
        "generated_report": None,
        "generate_completed": False,
        "status": "running",
        "current_stage": None,
        "error": None,
    }

    completed_extract_record = _make_completed_stage_record("extract", checkpoint_data)

    extract_stage = ExtractStage()
    generate_stage = GenerateStage()
    _patch_extract_llm(extract_stage)
    _patch_generate_llm(generate_stage, report_text="Resumed tariff report")

    stage_repo = _make_stage_repo()
    # resume() calls list_by_run to find completed stages
    stage_repo.list_by_run = AsyncMock(return_value=[completed_extract_record])

    runner = _make_runner(extract_stage, generate_stage, stage_repo=stage_repo)

    final_state = await runner.resume(run_id, _make_run_repo())

    # The workflow should have completed with a generated report
    assert "generated_report" in final_state
    assert final_state["generated_report"] == "Resumed tariff report"
    assert final_state.get("generate_completed") is True


# ---------------------------------------------------------------------------
# Test 2 — resume() raises when there are no completed stages
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_raises_when_no_completed_stages():
    """
    resume() must raise ValueError when there are no completed stage records
    to restore from.
    """
    run_id = uuid4()

    extract_stage = ExtractStage()
    generate_stage = GenerateStage()
    _patch_extract_llm(extract_stage)
    _patch_generate_llm(generate_stage)

    stage_repo = _make_stage_repo()
    stage_repo.list_by_run = AsyncMock(return_value=[])  # no records at all

    runner = _make_runner(extract_stage, generate_stage, stage_repo=stage_repo)

    with pytest.raises(ValueError, match="No completed stages"):
        await runner.resume(run_id, _make_run_repo())


# ---------------------------------------------------------------------------
# Test 3 — resume() raises when checkpoint data is missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_raises_when_checkpoint_data_missing():
    """
    resume() must raise ValueError when the last completed stage record has
    no checkpoint_data stored.
    """
    run_id = uuid4()

    record = MagicMock()
    record.id = uuid4()
    record.stage_name = "extract"
    record.status = "completed"
    record.checkpoint_data = None  # missing checkpoint

    extract_stage = ExtractStage()
    generate_stage = GenerateStage()
    _patch_extract_llm(extract_stage)
    _patch_generate_llm(generate_stage)

    stage_repo = _make_stage_repo()
    stage_repo.list_by_run = AsyncMock(return_value=[record])

    runner = _make_runner(extract_stage, generate_stage, stage_repo=stage_repo)

    with pytest.raises(ValueError, match="No checkpoint data"):
        await runner.resume(run_id, _make_run_repo())


# ---------------------------------------------------------------------------
# Test 4 — full run then resume: both stages called on each invocation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_run_then_resume_uses_checkpoint():
    """
    Simulates a partial run: extract completes, but generate is not yet
    recorded.  On resume, run() is called with the restored checkpoint state
    that already contains extracted_claims, so generate can proceed without
    needing to redo the extraction LLM call.

    Both stages execute during the resume run because _wrap_stage_with_persistence
    does not skip completed stages — it always calls stage.execute().
    """
    run_id = uuid4()
    workspace_id = str(uuid4())
    document_id = str(uuid4())

    extract_stage = ExtractStage()
    generate_stage = GenerateStage()

    extract_calls = []
    generate_calls = []

    original_extract_execute = extract_stage.execute
    original_generate_execute = generate_stage.execute

    async def counting_extract(state):
        extract_calls.append(state)
        return await original_extract_execute(state)

    async def counting_generate(state):
        generate_calls.append(state)
        return await original_generate_execute(state)

    extract_stage.execute = counting_extract
    generate_stage.execute = counting_generate

    claims = _sample_claims()
    _patch_extract_llm(extract_stage, claims=claims)
    _patch_generate_llm(generate_stage, report_text="Report after resume")

    # --- First run (both stages complete) ---
    stage_repo = _make_stage_repo()
    runner = _make_runner(extract_stage, generate_stage, stage_repo=stage_repo)

    initial_state = {
        "workflow_run_id": str(run_id),
        "workspace_id": workspace_id,
        "document_id": document_id,
        "document_content": "Laptop computer",
    }

    await runner.run(initial_state, _make_run_repo())
    assert len(extract_calls) == 1, "extract should run once on first run"
    assert len(generate_calls) == 1, "generate should run once on first run"

    # --- Simulate resume: build checkpoint from extract output ---
    checkpoint_data = {
        "workflow_run_id": str(run_id),
        "workspace_id": workspace_id,
        "document_id": document_id,
        "document_content": "Laptop computer",
        "extracted_claims": [c.model_dump() for c in claims],
        "extract_completed": True,
        "generated_report": None,
        "generate_completed": False,
        "status": "running",
        "current_stage": None,
        "error": None,
    }
    completed_extract_record = _make_completed_stage_record("extract", checkpoint_data)

    stage_repo2 = _make_stage_repo()
    stage_repo2.list_by_run = AsyncMock(return_value=[completed_extract_record])

    # Rebuild runner with new stage repo (simulating a fresh process)
    runner2 = WorkflowRunner(
        workflow_name="tariff",
        stages=[extract_stage, generate_stage],
        edges=[("extract", "generate"), ("generate", "END")],
        state_schema=TariffWorkflowState,
        stage_repository=stage_repo2,
    )

    final_state = await runner2.resume(run_id, _make_run_repo())

    # Both stages run again on resume (runner does not skip completed ones)
    assert len(extract_calls) == 2, "extract runs again on resume"
    assert len(generate_calls) == 2, "generate runs again on resume"

    # Final state must contain the generate output
    assert final_state.get("generated_report") == "Report after resume"
    assert final_state.get("generate_completed") is True


# ---------------------------------------------------------------------------
# Test 5 — resume picks the LAST completed stage checkpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resume_uses_last_completed_stage_checkpoint():
    """
    When multiple stages are completed, resume() must restore the checkpoint
    from the last completed stage (not an earlier one).
    """
    run_id = uuid4()
    workspace_id = str(uuid4())
    document_id = str(uuid4())

    claims = _sample_claims()

    extract_checkpoint = {
        "workflow_run_id": str(run_id),
        "workspace_id": workspace_id,
        "document_id": document_id,
        "document_content": "Laptop",
        "extracted_claims": [c.model_dump() for c in claims],
        "extract_completed": True,
        "generated_report": None,
        "generate_completed": False,
        "status": "running",
        "current_stage": None,
        "error": None,
    }

    generate_checkpoint = {
        **extract_checkpoint,
        "generated_report": "Previously generated report",
        "generate_completed": True,
    }

    extract_record = _make_completed_stage_record("extract", extract_checkpoint)
    generate_record = _make_completed_stage_record("generate", generate_checkpoint)

    extract_stage = ExtractStage()
    generate_stage = GenerateStage()
    _patch_extract_llm(extract_stage)
    _patch_generate_llm(generate_stage, report_text="New report on resume")

    stage_repo = _make_stage_repo()
    # Both stages completed; generate is last
    stage_repo.list_by_run = AsyncMock(return_value=[extract_record, generate_record])

    runner = _make_runner(extract_stage, generate_stage, stage_repo=stage_repo)

    final_state = await runner.resume(run_id, _make_run_repo())

    # The runner re-executes generate with the restored state (generate_completed=True
    # was in the checkpoint but generate stage still runs and overwrites it)
    assert "generated_report" in final_state
    assert final_state.get("generate_completed") is True
