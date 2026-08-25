"""
@file: backend/tests/test_resume.py
@description: Proves the run survives being stopped. Simulates a process kill partway
    through the pipeline, then restarts and asserts the run continues from the saved
    stage rather than starting over — and that stages completed before the kill make no
    further LLM calls.
@flow: run the graph with a node rigged to raise mid-pipeline -> assert earlier stages
    are checkpointed COMPLETE -> clear the LLM call log (simulating a fresh process) ->
    re-execute -> assert the completed stages made zero new calls and the run advanced.
@dependencies:
    - conftest fixtures: test_db, fake_groq, fake_superdocs
"""

from __future__ import annotations

import pytest

from backend.agents.graph import create_run, execute_run, load_state
from backend.db.database import session_scope
from backend.models import Run, RunStatus

pytestmark = pytest.mark.asyncio


class SimulatedKill(RuntimeError):
    """Stands in for the process being killed mid-run."""


async def test_run_resumes_from_saved_stage(
    test_db, fake_groq, fake_superdocs, sample_csv, monkeypatch
):
    run_uuid = await create_run(str(sample_csv), None)

    # Rig the theme stage to die, as if the process were killed during it.
    from backend.agents.nodes.theme import ThemeNode

    original_run = ThemeNode.run

    async def exploding_run(self, state, rid):
        raise SimulatedKill("process killed during theming")

    monkeypatch.setattr(ThemeNode, "run", exploding_run)

    result = await execute_run(run_uuid)
    assert result["status"] == RunStatus.FAILED.value

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        stages = (run.checkpoint_data or {}).get("stages", {})

    # Work completed before the kill must be durable.
    assert stages["ingest"]["status"] == "COMPLETE"
    assert stages["classify"]["status"] == "COMPLETE"
    assert stages["extract"]["status"] == "COMPLETE"
    assert stages["theme"]["status"] == "FAILED"
    assert "superdocs" not in stages, "later stages must not have run"

    calls_before_restart = len(fake_groq.calls)
    assert calls_before_restart > 0, "the first pass should have called the LLM"

    # --- restart: repair the node and re-execute, as a fresh process would ---
    monkeypatch.setattr(ThemeNode, "run", original_run)
    fake_groq.calls = []  # a new process has no memory of prior calls

    result2 = await execute_run(run_uuid)
    assert result2["paused"] is True
    assert result2["status"] == RunStatus.AWAITING_APPROVAL.value

    # Ingest, classify and extract were already done. On resume they must be skipped
    # entirely — no LLM calls for classify or extract in this second pass.
    systems = " ".join(c["system"] for c in fake_groq.calls)
    assert "classify customer-support records" not in systems, (
        "classify re-ran after resume — checkpoint skip is not working"
    )
    assert "extract structured facts" not in systems, (
        "extract re-ran after resume — checkpoint skip is not working"
    )

    state = await load_state(run_uuid)
    assert state["conversations_ingested"] == 6, "state must survive the restart"
    assert state["theme_count"] >= 1, "theming should have completed on resume"


async def test_resume_preserves_prior_state_values(
    test_db, fake_groq, fake_superdocs, sample_csv, monkeypatch
):
    """State written before a crash must be readable after it, not recomputed."""
    run_uuid = await create_run(str(sample_csv), None)

    from backend.agents.nodes.draft import DraftNode

    original = DraftNode.run

    async def boom(self, state, rid):
        raise SimulatedKill("killed during drafting")

    monkeypatch.setattr(DraftNode, "run", boom)
    await execute_run(run_uuid)

    state_after_crash = await load_state(run_uuid)
    themes_before = state_after_crash["theme_count"]
    quotes_before = state_after_crash["quotes_anonymized"]
    assert themes_before >= 1 and quotes_before >= 1

    monkeypatch.setattr(DraftNode, "run", original)
    await execute_run(run_uuid)

    state_after_resume = await load_state(run_uuid)
    assert state_after_resume["theme_count"] == themes_before
    assert state_after_resume["quotes_anonymized"] == quotes_before


async def test_paused_run_is_marked_resumable(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        assert run.is_resumable is True
        assert run.is_terminal is False
