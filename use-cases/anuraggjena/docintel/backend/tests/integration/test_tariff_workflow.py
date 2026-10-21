"""
Integration tests for the full tariff classification workflow.

LLM provider calls are mocked; everything else (WorkflowRunner, stages,
state passing) uses real code.

Key state keys (confirmed from source):
- ExtractStage returns: {"extracted_claims": [...], "extract_completed": True}
- GenerateStage returns: {"generated_report": "...", "generate_completed": True}

WorkflowRunner.__init__ signature:
    workflow_name, stages, edges, state_schema, stage_repository

WorkflowRunner.run() signature:
    initial_state, run_repository
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from backend.core.workflow.runner import WorkflowRunner
from backend.modules.tariff.stages.extract import ExtractStage
from backend.modules.tariff.stages.generate import GenerateStage
from backend.modules.tariff.schemas import TariffClaim, TariffWorkflowState
from backend.modules.tariff.stages.extract import TariffClaimsResponse


def _make_stage_repo():
    """Return a mock WorkflowStageRepository."""
    repo = AsyncMock()
    repo.get_by_run_and_name = AsyncMock(return_value=None)
    repo.create = AsyncMock(return_value=MagicMock(id=uuid4()))
    repo.update = AsyncMock(return_value=MagicMock())
    return repo


def _make_run_repo():
    """Return a mock WorkflowRunRepository."""
    repo = AsyncMock()
    repo.update = AsyncMock(return_value=MagicMock())
    return repo


def _make_runner(extract_stage, generate_stage, stage_repo=None):
    """Build a WorkflowRunner wired for extract → generate."""
    return WorkflowRunner(
        workflow_name="tariff",
        stages=[extract_stage, generate_stage],
        edges=[("extract", "generate"), ("generate", "END")],
        state_schema=TariffWorkflowState,
        stage_repository=stage_repo or _make_stage_repo(),
    )


def _initial_state(**overrides):
    """Return a minimal valid initial state dict."""
    base = {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "document_content": "This is a laptop computer used for portable computing.",
    }
    base.update(overrides)
    return base


def _sample_claims():
    return [
        TariffClaim(
            hs_code="8471.30",
            description="Laptop computer",
            duty_rate="0%",
        )
    ]


def _patch_extract_llm(stage: ExtractStage, claims=None):
    """Replace the stage's llm with a mock that returns a TariffClaimsResponse."""
    if claims is None:
        claims = _sample_claims()
    mock_llm = MagicMock()
    mock_llm.generate_structured = AsyncMock(
        return_value=TariffClaimsResponse(claims=claims)
    )
    stage.llm = mock_llm
    return mock_llm


def _patch_generate_llm(stage: GenerateStage, report_text=None):
    """Replace the stage's llm with a mock that returns a report string."""
    if report_text is None:
        report_text = "Tariff Classification Report\n\nHS Code: 8471.30\nDuty Rate: 0%"
    mock_llm = MagicMock()
    response = MagicMock()
    response.content = report_text
    mock_llm.generate = AsyncMock(return_value=response)
    stage.llm = mock_llm
    return mock_llm


@pytest.mark.asyncio
async def test_full_tariff_workflow_extracts_and_generates():
    """Full integration: state flows from extract stage to generate stage."""
    extract_stage = ExtractStage()
    generate_stage = GenerateStage()

    _patch_extract_llm(extract_stage)
    _patch_generate_llm(generate_stage)

    runner = _make_runner(extract_stage, generate_stage)
    final_state = await runner.run(_initial_state(), _make_run_repo())

    # Extract stage must have produced claims
    assert "extracted_claims" in final_state
    assert final_state["extracted_claims"], "expected non-empty extracted_claims"
    assert final_state.get("extract_completed") is True

    # Generate stage must have produced a report
    assert "generated_report" in final_state
    assert final_state["generated_report"], "expected non-empty generated_report"
    assert final_state.get("generate_completed") is True


@pytest.mark.asyncio
async def test_tariff_workflow_state_passes_between_stages():
    """State from extract stage is visible in generate stage."""
    extract_stage = ExtractStage()
    generate_stage = GenerateStage()

    _patch_extract_llm(extract_stage)
    captured_states = []

    original_generate_execute = generate_stage.execute

    async def capturing_execute(state):
        captured_states.append(
            state.model_dump() if hasattr(state, "model_dump") else dict(state)
        )
        return await original_generate_execute(state)

    generate_stage.execute = capturing_execute
    _patch_generate_llm(generate_stage)

    runner = _make_runner(extract_stage, generate_stage)
    await runner.run(_initial_state(), _make_run_repo())

    assert len(captured_states) > 0, "GenerateStage.execute was never called"
    generate_input = captured_states[0]

    assert "extracted_claims" in generate_input, (
        f"Generate stage missing 'extracted_claims'. Keys seen: {list(generate_input.keys())}"
    )
    assert generate_input["extracted_claims"], "extracted_claims was empty when generate ran"


@pytest.mark.asyncio
async def test_tariff_workflow_claims_content_is_correct():
    """Verify the extracted claims content survives the round-trip through state."""
    extract_stage = ExtractStage()
    generate_stage = GenerateStage()

    claims = [
        TariffClaim(hs_code="8471.30", description="Laptop computer", duty_rate="0%"),
        TariffClaim(hs_code="8517.12", description="Mobile phone", duty_rate="2.5%"),
    ]
    _patch_extract_llm(extract_stage, claims=claims)
    _patch_generate_llm(generate_stage)

    runner = _make_runner(extract_stage, generate_stage)
    final_state = await runner.run(_initial_state(), _make_run_repo())

    result_claims = final_state["extracted_claims"]
    assert len(result_claims) == 2

    # LangGraph may deserialise claims as dicts or Pydantic models
    def get_field(claim, field):
        return claim[field] if isinstance(claim, dict) else getattr(claim, field)

    hs_codes = {get_field(c, "hs_code") for c in result_claims}
    assert "8471.30" in hs_codes
    assert "8517.12" in hs_codes


@pytest.mark.asyncio
async def test_tariff_workflow_handles_empty_document_in_extract():
    """GenerateStage raises when extract returns no claims; verify the error is propagated."""
    extract_stage = ExtractStage()
    generate_stage = GenerateStage()

    # Extract returns empty list
    mock_llm = MagicMock()
    mock_llm.generate_structured = AsyncMock(
        return_value=TariffClaimsResponse(claims=[])
    )
    extract_stage.llm = mock_llm
    _patch_generate_llm(generate_stage)

    runner = _make_runner(extract_stage, generate_stage)

    # GenerateStage.execute raises ValueError when extracted_claims is empty
    with pytest.raises(Exception):
        await runner.run(_initial_state(document_content=""), _make_run_repo())


@pytest.mark.asyncio
async def test_tariff_workflow_generate_report_contains_hs_code():
    """Generated report text is stored in final state and matches LLM output."""
    expected_report = "HS Code 8471.30 — duty free"

    extract_stage = ExtractStage()
    generate_stage = GenerateStage()

    _patch_extract_llm(extract_stage)
    _patch_generate_llm(generate_stage, report_text=expected_report)

    runner = _make_runner(extract_stage, generate_stage)
    final_state = await runner.run(_initial_state(), _make_run_repo())

    assert final_state["generated_report"] == expected_report
