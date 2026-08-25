"""
@file: backend/tests/test_concurrent.py
@description: Proves two runs execute simultaneously without contaminating each other.
    Every table is scoped by run_id and the checkpoint lock is per-row, so concurrent
    runs should proceed in parallel with completely separate state.
@flow: create two runs over different input files -> execute both with asyncio.gather ->
    assert each has its own conversations, themes, approval items and checkpoints, and
    that no row from one run is visible under the other's id.
@dependencies:
    - conftest fixtures: test_db, fake_groq, fake_superdocs
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.agents.graph import create_run, execute_run, load_state
from backend.db.database import session_scope
from backend.models import ApprovalItem, Conversation, Run, RunStatus, Theme

pytestmark = pytest.mark.asyncio


def _write_csv(path: Path, rows: list[str]) -> Path:
    lines = ["text,date"]
    for i, text in enumerate(rows):
        lines.append(f'"{text}",2026-07-{(i % 28) + 1:02d}')
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


async def test_two_runs_execute_with_isolated_state(
    test_db, fake_groq, fake_superdocs, tmp_path
):
    csv_a = _write_csv(
        tmp_path / "a.csv",
        [
            "Export keeps failing and no file is produced at all when I click download.",
            "The export button does nothing whatsoever and blocks my reporting workflow.",
        ],
    )
    csv_b = _write_csv(
        tmp_path / "b.csv",
        [
            "Dashboard is painfully slow to load every single morning without exception.",
            "Loading the main dashboard takes far too long with many projects open.",
            "Dashboard performance has degraded badly over the past few weeks for us.",
        ],
    )

    run_a = await create_run(str(csv_a), None, quarter_label="Q3 2026")
    run_b = await create_run(str(csv_b), None, quarter_label="Q3 2026")
    assert run_a != run_b

    # Execute both at once. If state leaked, counts would cross-contaminate.
    results = await asyncio.gather(execute_run(run_a), execute_run(run_b))
    assert all(r["paused"] for r in results), "both should reach the human gate"

    state_a = await load_state(run_a)
    state_b = await load_state(run_b)
    assert state_a["conversations_ingested"] == 2
    assert state_b["conversations_ingested"] == 3

    async with session_scope() as session:
        conv_a = list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_a)
                )
            ).scalars()
        )
        conv_b = list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_b)
                )
            ).scalars()
        )
        assert len(conv_a) == 2 and len(conv_b) == 3
        assert {c.source_file for c in conv_a} == {"a.csv"}
        assert {c.source_file for c in conv_b} == {"b.csv"}

        themes_a = list(
            (await session.execute(select(Theme).where(Theme.run_id == run_a))).scalars()
        )
        themes_b = list(
            (await session.execute(select(Theme).where(Theme.run_id == run_b))).scalars()
        )
        assert themes_a and themes_b
        assert not ({t.id for t in themes_a} & {t.id for t in themes_b})

        items_a = list(
            (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_a)
                )
            ).scalars()
        )
        items_b = list(
            (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_b)
                )
            ).scalars()
        )
        assert items_a and items_b
        assert not ({i.id for i in items_a} & {i.id for i in items_b})


async def test_checkpoints_do_not_cross_contaminate(
    test_db, fake_groq, fake_superdocs, tmp_path
):
    csv_a = _write_csv(tmp_path / "x.csv", ["Export fails and produces nothing at all."])
    csv_b = _write_csv(
        tmp_path / "y.csv",
        ["Notification emails never arrive even after retrying several times."],
    )
    run_a = await create_run(str(csv_a), None)
    run_b = await create_run(str(csv_b), None)

    await asyncio.gather(execute_run(run_a), execute_run(run_b))

    async with session_scope() as session:
        a = await session.get(Run, run_a)
        b = await session.get(Run, run_b)
        assert a.input_path.endswith("x.csv")
        assert b.input_path.endswith("y.csv")
        # Each run keeps its own cost ledger.
        assert a.cost_report["totals"]["groq_tokens_used"] > 0
        assert b.cost_report["totals"]["groq_tokens_used"] > 0
        assert a.checkpoint_data["stages"].keys() == b.checkpoint_data["stages"].keys()
        assert a.status == b.status == RunStatus.AWAITING_APPROVAL


async def test_same_run_executed_twice_does_not_duplicate_work(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Two concurrent executions of the SAME run must not double-process it.

    This is the case the row lock exists for: the completeness check and the claim
    happen in one locked transaction, so only one execution does the work.
    """
    run_uuid = await create_run(str(sample_csv), None)
    await asyncio.gather(execute_run(run_uuid), execute_run(run_uuid))

    async with session_scope() as session:
        conversations = list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_uuid)
                )
            ).scalars()
        )
    # Ingest running twice would have produced 12 rows, or violated the uniqueness
    # constraint on (run_id, source_file, source_line).
    assert len(conversations) == 6
