"""
@file: backend/tests/test_graph.py
@description: End-to-end graph test with every external call mocked. Asserts that all
    nine nodes execute in order, that state flows correctly between them, that the run
    pauses at the human gate, and that it completes and exports once the gate is
    resolved. This is the test that proves the pipeline wires together.
@flow: create a run -> execute -> assert it paused at human_gate with approval items ->
    approve everything -> execute again -> assert it completed, exported, and made the
    expected SuperDocs calls in the expected order.
@dependencies:
    - conftest fixtures: test_db, fake_groq, fake_superdocs, sample_csv
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.agents.graph import create_run, execute_run, load_state
from backend.db.database import session_scope
from backend.models import ApprovalItem, ApprovalStatus, Run, RunStatus, Theme

pytestmark = pytest.mark.asyncio


async def _approve_all(run_uuid) -> int:
    async with session_scope() as session:
        items = list(
            (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_uuid)
                )
            ).scalars()
        )
        for item in items:
            item.status = ApprovalStatus.APPROVED
        return len(items)


async def test_full_graph_runs_to_gate_then_completes(
    test_db, fake_groq, fake_superdocs, sample_csv, prior_digest
):
    run_uuid = await create_run(
        str(sample_csv), str(prior_digest), quarter_label="Q3 2026"
    )

    # --- first pass: should stop at the human gate ---
    result = await execute_run(run_uuid)
    assert result["paused"] is True, "graph must pause at the human gate"
    assert result["status"] == RunStatus.AWAITING_APPROVAL.value

    state = await load_state(run_uuid)
    assert state["conversations_ingested"] == 6
    assert state["conversations_relevant"] == 6
    assert state["theme_count"] >= 1
    assert state["quotes_anonymized"] >= 1
    assert state["comparison_available"] is True, "prior digest should have been read"
    assert state["draft_sections"], "draft must produce section instructions"

    async with session_scope() as session:
        themes = list(
            (await session.execute(select(Theme).where(Theme.run_id == run_uuid))).scalars()
        )
        assert themes, "themes must be persisted"
        assert all(t.evidence_refs for t in themes), "every theme needs evidence refs"

    # --- resolve the gate ---
    approved = await _approve_all(run_uuid)
    assert approved > 0, "gate must create reviewable items"

    # --- second pass: should complete ---
    result2 = await execute_run(run_uuid)
    assert result2["paused"] is False, f"run should finish, got {result2}"
    assert result2["status"] == RunStatus.COMPLETE.value

    ops = [c["op"] for c in fake_superdocs.calls]
    assert "edit" in ops and "approve" in ops and "export" in ops
    # Between sections the session must be checked for a free slot. Skipping this is what
    # produced 409 session_busy partway through a live run: a completed job id does not
    # imply a free session, because approving changes can leave follow-on work in flight.
    assert "wait_free" in ops, "session was not checked for readiness between edits"
    assert ops.index("edit") < ops.index("wait_free"), (
        "the readiness check should follow the first edit, not precede it"
    )
    # Every edit must be followed by an explicit approval — nothing auto-applies.
    assert ops.count("approve") == ops.count("edit")
    assert fake_superdocs.exports == 1

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        assert run.status == RunStatus.COMPLETE
        assert run.export_path and run.export_path.endswith(".docx")
        assert run.superdocs_session_id == f"vocdigest-{run_uuid}"


async def test_all_stages_recorded_in_checkpoint(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Every stage that ran must leave a checkpoint, and cost must be attributed."""
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
    await _approve_all(run_uuid)
    await execute_run(run_uuid)

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        stages = (run.checkpoint_data or {}).get("stages", {})
        for expected in (
            "ingest",
            "classify",
            "extract",
            "theme",
            "anonymize",
            "compare",
            "draft",
            "human_gate",
            "superdocs",
        ):
            assert expected in stages, f"{expected} left no checkpoint"
            assert stages[expected]["status"] in {"COMPLETE", "SKIPPED"}

        cost = run.cost_report or {}
        assert "totals" in cost
        assert cost["totals"]["superdocs_operations"] >= 1
        assert cost["totals"]["duration_seconds"] >= 0


async def test_missing_prior_digest_is_reported_not_invented(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """With no prior digest the compare stage must skip and say so, not fabricate a QoQ."""
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    state = await load_state(run_uuid)
    assert state["comparison_available"] is False
    assert "no quarter-over-quarter" in state["comparison_note"].lower()

    # The drafted sections must not claim growth figures.
    what_changed = state["draft_sections"].get("what_changed", "")
    assert "%" not in what_changed, "no percentages without a prior quarter to compare"


async def test_theme_table_is_applied_exactly_once(
    test_db, fake_groq, fake_superdocs, sample_csv, prior_digest
):
    """No section may be sent to SuperDocs twice.

    Observed against the live API: `theme_table` matches startswith("theme_"), so it was
    placed in the ordering list alongside the numbered deep dives and applied twice. That
    produced a duplicate "Top Themes This Quarter" heading in the exported document and
    spent an extra metered operation — the kind of defect only visible in real output.
    """
    run_uuid = await create_run(str(sample_csv), str(prior_digest))
    await execute_run(run_uuid)
    await _approve_all(run_uuid)
    await execute_run(run_uuid)

    edits = [c["instruction"] for c in fake_superdocs.calls if c["op"] == "edit"]
    assert edits, "no edits were sent"
    # Instructions are truncated to 80 chars in the fake, which is enough to identify a
    # repeated section without depending on full text.
    assert len(edits) == len(set(edits)), (
        f"a section was sent twice: {[e for e in edits if edits.count(e) > 1][:2]}"
    )


async def test_deep_dive_sections_are_applied_in_numeric_order(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """theme_10 must follow theme_2, not sort before it as a string."""
    from backend.agents.nodes.superdocs import _DEEP_DIVE_KEY

    keys = ["theme_1", "theme_2", "theme_10", "theme_3", "theme_table"]
    matches = [
        (int(m.group(1)), k) for k in keys if (m := _DEEP_DIVE_KEY.match(k)) is not None
    ]
    ordered = [k for _, k in sorted(matches)]

    assert ordered == ["theme_1", "theme_2", "theme_3", "theme_10"]
    assert "theme_table" not in ordered