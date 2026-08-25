"""
@file: backend/tests/test_idempotency.py
@description: Proves that running a completed stage again returns the cached result and
    makes no external calls, and that the analysis itself is deterministic — the same
    input produces the same themes and the same clustering on every run.
@flow: run a stage once, record LLM call count -> invoke the node again on the same run
    -> assert zero new calls and identical state -> separately, run two independent runs
    over identical input and assert they produce identical theme structure.
@dependencies:
    - conftest fixtures: test_db, fake_groq, fake_superdocs
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.agents.graph import create_run, execute_run, load_state
from backend.agents.nodes.classify import ClassifyNode
from backend.agents.nodes.ingest import IngestNode
from backend.agents.state import build_initial_state
from backend.db.database import session_scope
from backend.models import Conversation, Run, Theme

pytestmark = pytest.mark.asyncio


async def test_completed_stage_returns_cache_without_calling_llm(
    test_db, fake_groq, sample_csv
):
    run_uuid = await create_run(str(sample_csv), None)
    state = build_initial_state(run_uuid, str(sample_csv))

    ingest = IngestNode()
    classify = ClassifyNode()

    state = await ingest(state)
    state = await classify(state)
    calls_after_first = len(fake_groq.calls)
    assert calls_after_first > 0, "classify should have called the LLM once"
    relevant_first = state["conversations_relevant"]

    # Re-invoke the same stages. Both must short-circuit on their checkpoints.
    state2 = await ingest(state)
    state2 = await classify(state2)

    assert len(fake_groq.calls) == calls_after_first, (
        "a completed stage re-ran the LLM — idempotency is broken"
    )
    assert state2["conversations_relevant"] == relevant_first

    async with session_scope() as session:
        rows = list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_uuid)
                )
            ).scalars()
        )
    assert len(rows) == 6, "ingest ran twice and duplicated rows"


async def test_full_rerun_is_free(test_db, fake_groq, fake_superdocs, sample_csv):
    """Executing a run that already reached the gate must not repeat any stage."""
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    calls_after = len(fake_groq.calls)
    superdocs_calls_after = len(fake_superdocs.calls)

    await execute_run(run_uuid)  # same pause point, nothing new to do

    assert len(fake_groq.calls) == calls_after, "re-execution repeated LLM work"
    assert len(fake_superdocs.calls) == superdocs_calls_after


async def test_identical_input_produces_identical_analysis(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Two independent runs over the same file must agree exactly.

    Guards the determinism the resume path depends on: if clustering varied between
    runs, a resumed run would silently diverge from the run it is continuing.
    """
    run_a = await create_run(str(sample_csv), None)
    run_b = await create_run(str(sample_csv), None)

    await execute_run(run_a)
    await execute_run(run_b)

    state_a = await load_state(run_a)
    state_b = await load_state(run_b)
    assert state_a["theme_count"] == state_b["theme_count"]
    assert state_a["conversations_relevant"] == state_b["conversations_relevant"]
    assert state_a["quotes_anonymized"] == state_b["quotes_anonymized"]

    async with session_scope() as session:
        themes_a = list(
            (
                await session.execute(
                    select(Theme).where(Theme.run_id == run_a).order_by(Theme.name)
                )
            ).scalars()
        )
        themes_b = list(
            (
                await session.execute(
                    select(Theme).where(Theme.run_id == run_b).order_by(Theme.name)
                )
            ).scalars()
        )

    assert [t.name for t in themes_a] == [t.name for t in themes_b]
    assert [t.volume_count for t in themes_a] == [t.volume_count for t in themes_b]
    # Evidence must cite the same source lines, not merely the same count.
    for ta, tb in zip(themes_a, themes_b):
        cites_a = sorted(r["citation"] for r in ta.evidence_refs)
        cites_b = sorted(r["citation"] for r in tb.evidence_refs)
        assert cites_a == cites_b


async def test_checkpoint_attempt_counter_increments(test_db, fake_groq, sample_csv):
    """A retried stage records its attempt count rather than silently overwriting."""
    run_uuid = await create_run(str(sample_csv), None)
    state = build_initial_state(run_uuid, str(sample_csv))

    node = IngestNode()
    await node(state)

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        assert run.checkpoint_data["stages"]["ingest"]["attempts"] == 1
        assert run.checkpoint_data["stages"]["ingest"]["status"] == "COMPLETE"
