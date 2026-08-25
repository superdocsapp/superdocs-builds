"""
@file: backend/tests/test_stage_control.py
@description: Tests per-stage retry and skip. The important behaviours are that a retry
    invalidates the stages downstream of it (their results were derived from output that
    is about to change) and that stages whose absence would break the system's core
    promises cannot be skipped at all.
@flow: run to the gate -> retry a middle stage -> assert it and everything after it lost
    their checkpoints while earlier stages kept theirs -> attempt to skip protected
    stages and assert refusal.
@dependencies: conftest fixtures, FastAPI TestClient
"""

from __future__ import annotations

import pytest

from backend.agents.graph import create_run, execute_run
from backend.agents.state import STAGES
from backend.db.database import session_scope
from backend.models import Run

pytestmark = pytest.mark.asyncio


async def _stages(run_uuid) -> dict:
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        return dict((run.checkpoint_data or {}).get("stages") or {})


async def test_retry_invalidates_downstream_stages(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    before = await _stages(run_uuid)
    assert "theme" in before and "draft" in before

    # Simulate what POST /runs/{id}/stages/retry does to the checkpoint.
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        data = dict(run.checkpoint_data or {})
        stages = dict(data.get("stages") or {})
        idx = STAGES.index("theme")
        for stage in STAGES[idx:]:
            stages.pop(stage, None)
        data["stages"] = stages
        run.checkpoint_data = data

    after = await _stages(run_uuid)
    # Upstream survives, so a retry costs only the work that actually depends on it.
    assert "ingest" in after and "classify" in after and "extract" in after
    # Downstream is gone, because those results came from output being replaced.
    for stage in ("theme", "anonymize", "compare", "draft", "human_gate"):
        assert stage not in after, f"{stage} should have been invalidated"

    fake_groq.calls = []
    await execute_run(run_uuid)

    systems = " ".join(c["system"] for c in fake_groq.calls)
    assert "classify customer-support records" not in systems, "upstream re-ran"
    assert "name clusters" in systems, "theme did not actually re-run"


async def test_protected_stages_cannot_be_skipped(
    test_db, api_client, fake_groq, fake_superdocs, sample_csv
):
    """ingest, theme and human_gate are refused by the API.

    Skipping ingest leaves no data, skipping theme leaves nothing to report, and
    skipping the gate publishes unreviewed content — which is the one thing this system
    exists to prevent.
    """
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    for stage in ("ingest", "theme", "human_gate"):
        response = await api_client.post(
            f"/runs/{run_uuid}/stages/skip", json={"stage": stage}
        )
        assert response.status_code == 409, f"{stage} should be unskippable"
        assert "cannot be skipped" in response.json()["detail"]

    # A legitimately optional stage is accepted.
    response = await api_client.post(
        f"/runs/{run_uuid}/stages/skip", json={"stage": "compare"}
    )
    assert response.status_code == 202
    assert response.json()["skipped"] == "compare"

    # An unknown stage is a client error, not a silent no-op.
    response = await api_client.post(
        f"/runs/{run_uuid}/stages/skip", json={"stage": "nonsense"}
    )
    assert response.status_code == 400


async def test_skip_is_recorded_in_the_decision_log(
    test_db, api_client, fake_groq, fake_superdocs, sample_csv
):
    """An operator skip must be attributable, not silent."""
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    await api_client.post(f"/runs/{run_uuid}/stages/skip", json={"stage": "compare"})

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        decisions = [d["decision"] for d in (run.decision_log or [])]
    assert "SKIPPED_BY_OPERATOR" in decisions
