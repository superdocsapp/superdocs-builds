"""
@file: backend/tests/test_cancel_and_budget.py
@description: Tests operator cancellation and the per-run token budget. Both exist for
    the same reason: a provider's allowance is shared across every concurrent run on one
    key, so a forgotten or runaway run can exhaust it and make unrelated work appear
    broken. Cancellation is the manual control; the budget is the one that works when
    nobody is watching.
@flow: cancel a run mid-flight and assert it stops at the next stage boundary with
    completed stages intact -> assert a cancelled run is not resumable -> set a tiny
    budget and assert later stages degrade rather than continuing to spend.
@dependencies: conftest fixtures
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.agents.graph import create_run, execute_run, load_state
from backend.agents.nodes.base import NodeCancelled
from backend.config import settings
from backend.db.database import session_scope
from backend.models import Conversation, Run, RunStatus

pytestmark = pytest.mark.asyncio


async def test_cancel_stops_the_run_at_the_next_stage(
    test_db, fake_groq, fake_superdocs, sample_csv, monkeypatch
):
    """A cancelled run must stop, and must keep the stages that already finished."""
    run_uuid = await create_run(str(sample_csv), None)

    # Cancel from inside the extract stage, simulating an operator clicking Cancel while
    # the run is in flight.
    from backend.agents.nodes.extract import ExtractNode

    original = ExtractNode.run

    async def cancel_midway(self, state, rid):
        result = await original(self, state, rid)
        async with session_scope() as session:
            run = await session.get(Run, rid)
            run.status = RunStatus.CANCELLED
        return result

    monkeypatch.setattr(ExtractNode, "run", cancel_midway)

    result = await execute_run(run_uuid)
    assert result["status"] == RunStatus.CANCELLED.value
    assert result.get("cancelled") is True

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        stages = (run.checkpoint_data or {}).get("stages", {})
        conversations = list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_uuid)
                )
            ).scalars()
        )

    # Work done before the cancel survives.
    assert stages["ingest"]["status"] == "COMPLETE"
    assert stages["extract"]["status"] == "COMPLETE"
    assert len(conversations) == 6
    # Nothing after the cancellation point ran.
    assert "theme" not in stages
    assert "superdocs" not in stages


async def test_cancelled_run_is_not_resumable_via_api(
    test_db, api_client, fake_groq, fake_superdocs, sample_csv
):
    """Cancellation is final. A cancelled run must not offer a resume path."""
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)  # reaches the gate

    response = await api_client.post(f"/runs/{run_uuid}/cancel")
    assert response.status_code == 202
    body = response.json()
    assert body["cancelled_from"] == RunStatus.AWAITING_APPROVAL.value

    # Cancelling twice is a conflict, not a silent success.
    again = await api_client.post(f"/runs/{run_uuid}/cancel")
    assert again.status_code == 409

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        decisions = [d["decision"] for d in (run.decision_log or [])]
    assert "CANCEL_REQUESTED" in decisions


async def test_completed_run_cannot_be_cancelled(
    test_db, api_client, fake_groq, fake_superdocs, sample_csv
):
    from backend.models import ApprovalItem, ApprovalStatus

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
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
    await execute_run(run_uuid)

    response = await api_client.post(f"/runs/{run_uuid}/cancel")
    assert response.status_code == 409
    assert "COMPLETE" in response.json()["detail"]


async def test_token_budget_degrades_instead_of_spending(
    test_db, fake_groq, fake_superdocs, sample_csv, monkeypatch
):
    """Once a run passes its token budget, later stages must stop calling the model.

    This is the guardrail that does not require anyone to be watching. The observed
    failure it prevents: several concurrent runs quietly drained a shared daily allowance,
    so a later run appeared to break for no visible reason.
    """
    # Tiny budget: the first stage that spends anything will exceed it.
    monkeypatch.setattr(settings, "max_tokens_per_run", 250)

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        decisions = [d["decision"] for d in (run.decision_log or [])]
        spent = int(
            ((run.cost_report or {}).get("totals") or {}).get("groq_tokens_used", 0)
        )

    assert "BUDGET_REACHED" in decisions, "budget was never enforced"
    state = await load_state(run_uuid)
    assert state["degraded_stages"], "stages after the budget should have degraded"
    # Spend is bounded — not zero, since the stage that crossed the line had already run,
    # but nowhere near what an unbounded run would consume.
    assert spent < 3000, f"spend was not bounded: {spent} tokens"


async def test_budget_of_zero_disables_the_limit(
    test_db, fake_groq, fake_superdocs, sample_csv, monkeypatch
):
    monkeypatch.setattr(settings, "max_tokens_per_run", 0)

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        decisions = [d["decision"] for d in (run.decision_log or [])]
    assert "BUDGET_REACHED" not in decisions


async def test_active_runs_endpoint_reports_shared_spend(
    test_db, api_client, fake_groq, fake_superdocs, sample_csv
):
    """Concurrent runs must be visible, because they compete for one allowance."""
    run_a = await create_run(str(sample_csv), None)
    run_b = await create_run(str(sample_csv), None)

    response = await api_client.get("/runs/active/summary")
    assert response.status_code == 200
    body = response.json()
    # Both are PENDING and therefore counted as active.
    ids = {r["run_id"] for r in body["runs"]}
    assert str(run_a) in ids and str(run_b) in ids
    assert body["active_count"] >= 2
    assert "total_tokens_spent_by_active_runs" in body


async def test_node_cancelled_is_not_retried(test_db, fake_groq, sample_csv, monkeypatch):
    """Cancellation must not be swallowed by the generic retry path."""
    from backend.agents.nodes.ingest import IngestNode
    from backend.agents.state import build_initial_state

    run_uuid = await create_run(str(sample_csv), None)
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        run.status = RunStatus.CANCELLED

    node = IngestNode()
    state = build_initial_state(run_uuid, str(sample_csv))
    with pytest.raises(NodeCancelled):
        await node(state)

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        stages = (run.checkpoint_data or {}).get("stages", {})
    # The stage never claimed itself, so no attempt was recorded.
    assert "ingest" not in stages or stages["ingest"].get("attempts", 0) <= 1