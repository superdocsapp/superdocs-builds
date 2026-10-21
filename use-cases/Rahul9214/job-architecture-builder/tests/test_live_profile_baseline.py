"""Authoritative filled-profile publish and live duplicate-baseline repair."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_architecture.live.instructions import subset_profile_for_demo
from job_architecture.live.orchestrator import LiveOrchestrator
from job_architecture.profile_structure import validate_level_expectations_block
from job_architecture.superdocs.errors import SuperDocsError
from job_architecture.superdocs.models import ReviewDecision

from tests.live_fake import FakeProtocolClient
from tests.test_live_orchestration import _orchestrator


def test_start_profile_uploads_filled_docx_without_superdocs_fill(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    result = orch.start_profile()
    assert result.structure_ok is True
    assert result.document_id
    assert fake.edits == []
    assert "filled" in fake.uploads[-1] or fake.uploads[-1].startswith("profile-")
    state = orch.state()
    assert state.profile_integrity["status"] == "authoritative_upload"
    profile = subset_profile_for_demo(orch.framework, orch.subset)
    assert validate_level_expectations_block(profile.level_expectations).ok
    assert orch.profile_intent().estimated_count == 0


def test_surgical_update_refuses_superdocs_filled_live_baseline(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    orch.start_profile()
    state = orch.state()
    state.jobs["profile"] = {
        **(state.jobs.get("profile") or {}),
        "job_id": "job_offline_profile_fill",
        "source": "superdocs_fill",
        "status": "completed",
        "remote_job_status": "completed",
        "review_outcome": "approved",
        "mutation_applied": True,
    }
    state.profile_integrity = {}
    orch.store.save(state)
    resumed = LiveOrchestrator(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    assert resumed.state().profile_integrity["status"] == "needs_repair"
    intent = resumed.surgical_intent()
    assert intent.estimated_count == 0
    assert "repair-profile" in intent.summary
    with pytest.raises(SuperDocsError, match="structurally untrusted"):
        resumed.start_surgical_update()
    assert fake.edits == []


def test_repair_profile_is_reviewed_in_place_and_does_not_reupload(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    published = orch.start_profile()
    state = orch.state()
    state.jobs["profile"] = {
        **(state.jobs.get("profile") or {}),
        "job_id": "job_offline_profile_fill",
        "source": "superdocs_fill",
        "status": "completed",
        "mutation_applied": True,
        "review_outcome": "approved",
    }
    state.profile_integrity = {}
    orch.store.save(state)
    orch = LiveOrchestrator(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    uploads_before = list(fake.uploads)
    snapshot = orch.start_profile_repair()
    assert snapshot.status == "awaiting_approval"
    assert fake.uploads == uploads_before
    assert fake.edits[-1]["document_id"] == published.document_id
    message = fake.edits[-1]["message"]
    profile = subset_profile_for_demo(orch.framework, orch.subset)
    assert message.count(profile.level_expectations) == 1
    assert "duplicated" in message.lower()
    assert fake.edits[-1]["operation_key"] == "live-edit:profile_repair:1"
    approved = orch.submit_decisions("profile_repair", [ReviewDecision(change_id="ch_1", approved=True)])
    assert approved.status == "completed"
    assert orch.state().profile_integrity["status"] == "repair_pending_export_verify"
    with pytest.raises(SuperDocsError, match="verify-profile-structure"):
        orch.start_surgical_update()
    filled = tmp_path / "artifacts" / f"{profile.id}.docx"
    verified = orch.verify_profile_structure(filled)
    assert verified["ok"] is True
    assert verified["layout"]["paragraph_count"] >= 1
    assert verified["field_counts"]["scope"] == 1
    assert orch.state().profile_integrity["status"] == "verified"
    surgical = orch.start_surgical_update()
    assert surgical.status == "awaiting_approval"
    assert len(fake.edits) == 2


def test_rejected_surgical_history_is_preserved_across_repair(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    second = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    state = orch.state()
    state.jobs["profile"] = {
        **(state.jobs.get("profile") or {}),
        "job_id": "job_offline_profile_fill",
        "source": "superdocs_fill",
        "mutation_applied": True,
        "review_outcome": "approved",
        "status": "completed",
    }
    state.profile_integrity = {}
    orch.store.save(state)
    orch = LiveOrchestrator(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    with pytest.raises(SuperDocsError, match="structurally untrusted"):
        orch.start_surgical_update()
    surgical = orch.state().jobs["surgical"]
    assert surgical["job_id"] == second.job_id
    assert surgical["review_outcome"] == "rejected"
    assert surgical["mutation_applied"] is False
    assert surgical["history"][0]["job_id"] == first.job_id
    assert surgical["history"][0]["review_outcome"] == "rejected"
    assert surgical["attempt"] == 2
    orch.start_profile_repair()
    assert orch.state().jobs["surgical"]["job_id"] == second.job_id
    assert orch.state().jobs["surgical"]["history"][0]["job_id"] == first.job_id
