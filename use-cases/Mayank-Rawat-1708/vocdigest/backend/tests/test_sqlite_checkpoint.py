"""
@file: backend/tests/test_sqlite_checkpoint.py
@description: Tests the optional SQLite checkpoint mirror: that it records stage
    outcomes, that a run can be reconstructed from the file alone, and — most
    importantly — that a mirror failure never propagates into the run.
@flow: enable the mirror against a temp path -> run the graph -> assert checkpoints are
    present in the SQLite file and that recover_run() rebuilds the completed-stage list
    -> then break the mirror deliberately and assert the run still completes.
@dependencies: conftest fixtures, backend.db.sqlite_checkpoint
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.agents.graph import create_run, execute_run
from backend.config import settings
from backend.db import sqlite_checkpoint as scp
from backend.db.database import session_scope
from backend.models import ApprovalItem, ApprovalStatus

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mirror_enabled(tmp_path, monkeypatch):
    path = tmp_path / "checkpoints.db"
    monkeypatch.setattr(settings, "checkpoint_sqlite_path", str(path))
    return path


async def test_mirror_records_stage_checkpoints(
    test_db, fake_groq, fake_superdocs, sample_csv, mirror_enabled
):
    await scp.init_sqlite_checkpoints()
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    assert mirror_enabled.is_file(), "mirror file was never created"

    checkpoints = await scp.read_checkpoints(run_uuid)
    for stage in ("ingest", "classify", "extract", "theme", "anonymize", "draft"):
        assert stage in checkpoints, f"{stage} missing from the mirror"
        assert checkpoints[stage]["status"] == "COMPLETE"

    # The mirrored payload must carry real state, not an empty shell.
    assert checkpoints["ingest"]["result"]["state_delta"]["conversations_ingested"] == 6


async def test_run_recoverable_from_mirror_alone(
    test_db, fake_groq, fake_superdocs, sample_csv, mirror_enabled
):
    """The disaster case: reconstruct progress from the file with no Postgres."""
    await scp.init_sqlite_checkpoints()
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    recovered = await scp.recover_run(run_uuid)
    assert recovered is not None
    assert "ingest" in recovered["completed_stages"]
    assert "theme" in recovered["completed_stages"]
    assert recovered["recovered_from"].endswith("checkpoints.db")


async def test_mirror_failure_does_not_fail_the_run(
    test_db, fake_groq, fake_superdocs, sample_csv, monkeypatch, tmp_path
):
    """A broken mirror must be invisible to the run.

    The authoritative write has already committed by the time the mirror is attempted,
    so letting a mirror error surface would discard genuine progress.
    """
    # Point the mirror at a path that cannot be created.
    monkeypatch.setattr(
        settings, "checkpoint_sqlite_path", "/proc/nonexistent/nope/checkpoints.db"
    )

    run_uuid = await create_run(str(sample_csv), None)
    result = await execute_run(run_uuid)
    assert result["paused"] is True, "run should still reach the gate"

    async with session_scope() as session:
        items = list(
            (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_uuid)
                )
            ).scalars()
        )
    assert items, "gate items should exist despite the mirror being unwritable"
    assert all(i.status == ApprovalStatus.PENDING for i in items)


async def test_mirror_disabled_by_default(test_db, fake_groq, sample_csv):
    """With no path configured the mirror is inert and costs nothing."""
    assert scp.is_enabled() is False
    assert await scp.read_checkpoints(__import__("uuid").uuid4()) == {}
    assert await scp.list_mirrored_runs() == []
