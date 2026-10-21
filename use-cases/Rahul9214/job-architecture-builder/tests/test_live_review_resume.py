"""Reviewed-job resume state machine. Offline only; no live SuperDocs calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_architecture.live.instructions import surgical_update_plan
from job_architecture.live.job_state import (
    annotate_review,
    prepare_jobs,
    review_outcome_from_decisions,
    reviewed_job_action,
)
from job_architecture.live.orchestrator import LiveOrchestrator
from job_architecture.live.state import LiveState, RuntimeStore
from job_architecture.superdocs.errors import SuperDocsError
from job_architecture.superdocs.models import ReviewDecision

from tests.live_fake import FakeProtocolClient
from tests.test_live_orchestration import _orchestrator


def test_completed_rejected_is_not_applied_mutation() -> None:
    job = {
        "job_id": "job_offline_rejected",
        "status": "completed",
        "remote_job_status": "completed",
        "review_outcome": "rejected",
        "mutation_applied": False,
        "domain_applied": False,
        "review_decisions": [{"change_id": "ch_1", "approved": False}],
    }
    assert reviewed_job_action(job) == "new_edit"
    assert job["mutation_applied"] is False
    assert job["domain_applied"] is False


def test_completed_rejected_reviewed_job_does_not_count_as_completed_mutation(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    job = orch.state().jobs["surgical"]
    assert job["remote_job_status"] == "completed"
    assert job["review_outcome"] == "rejected"
    assert job["mutation_applied"] is False
    assert job["domain_applied"] is False
    intent = orch.surgical_intent()
    assert intent.estimated_count == 1
    assert fake.edits[0]["operation_key"] == "live-edit:surgical:1"
    assert "rejected" in intent.summary


def test_subsequent_surgical_update_creates_exactly_one_new_async_edit(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    second = orch.start_surgical_update()
    assert second.job_id != first.job_id
    assert len(fake.edits) == 2
    assert fake.edits[1]["operation_key"] == "live-edit:surgical:2"
    orch.start_surgical_update()
    assert len(fake.edits) == 2


def test_old_rejected_attempt_remains_in_history(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    orch.start_surgical_update()
    current = orch.state().jobs["surgical"]
    history = current["history"]
    assert len(history) == 1
    assert history[0]["job_id"] == first.job_id
    assert history[0]["review_outcome"] == "rejected"
    assert history[0]["mutation_applied"] is False
    assert history[0]["operation_key"] == "live-edit:surgical:1"
    assert current["job_id"] != first.job_id
    dumped = orch.store.path.read_text(encoding="utf-8")
    assert first.job_id in dumped
    assert '"review_outcome": "rejected"' in dumped


def test_completed_approved_does_not_duplicate(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=True)])
    job = orch.state().jobs["surgical"]
    assert job["review_outcome"] == "approved"
    assert job["mutation_applied"] is True
    assert job["domain_applied"] is False
    intent = orch.surgical_intent()
    assert intent.estimated_count == 0
    second = orch.start_surgical_update()
    assert second.job_id == first.job_id
    assert len(fake.edits) == 1


def test_awaiting_approval_resumes_instead_of_creating_another_edit(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    assert first.status == "awaiting_approval"
    assert orch.surgical_intent().estimated_count == 0
    second = orch.start_surgical_update()
    assert second.job_id == first.job_id
    assert len(fake.edits) == 1


def test_mixed_decisions_have_truthful_partial_semantics(tmp_path: Path) -> None:
    derived = review_outcome_from_decisions(
        [
            ReviewDecision(change_id="ch_keep", approved=True),
            ReviewDecision(change_id="ch_drop", approved=False),
        ]
    )
    assert derived["review_outcome"] == "mixed"
    assert derived["mutation_applied"] is True
    assert derived["partial_mutation"] is True
    assert derived["domain_applied"] is False
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    orch.submit_decisions(
        "surgical",
        [
            ReviewDecision(change_id="ch_1", approved=True),
            ReviewDecision(change_id="ch_2", approved=False),
        ],
    )
    job = orch.state().jobs["surgical"]
    assert job["review_outcome"] == "mixed"
    assert job["mutation_applied"] is True
    assert job["partial_mutation"] is True
    assert job["domain_applied"] is False
    assert job["review_decisions"] == [
        {"change_id": "ch_1", "approved": True},
        {"change_id": "ch_2", "approved": False},
    ]
    intent = orch.surgical_intent()
    assert intent.estimated_count == 0
    assert "Mixed" in intent.summary
    second = orch.start_surgical_update()
    assert second.job_id == first.job_id
    assert len(fake.edits) == 1


def test_rejected_attempt_does_not_advance_domain_dependency_version(tmp_path: Path) -> None:
    orch, _ = _orchestrator(tmp_path)
    _profile, old, planned, _plan = surgical_update_plan(orch.framework, orch.subset)
    assert planned.version == old.version + 1
    orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    after = orch.framework.level(old.id)
    assert after.version == old.version
    assert orch.state().jobs["surgical"]["domain_applied"] is False
    assert orch.domain_update_applied("surgical") is False


def test_corrected_approved_second_attempt_can_advance_state(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    _profile, old, _planned, _plan = surgical_update_plan(orch.framework, orch.subset)
    rejected_version = old.version
    second = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=True)])
    job = orch.state().jobs["surgical"]
    assert job["job_id"] == second.job_id
    assert job["review_outcome"] == "approved"
    assert job["mutation_applied"] is True
    assert job["domain_applied"] is False
    assert orch.framework.level(old.id).version == rejected_version
    assert orch.surgical_intent().estimated_count == 0
    third = orch.start_surgical_update()
    assert third.job_id == second.job_id
    assert len(fake.edits) == 2
    assert first.job_id != second.job_id
    assert orch.state().jobs["surgical"]["history"][0]["job_id"] == first.job_id


def test_process_restart_retains_review_resume_semantics(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    restarted = LiveOrchestrator(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    job = restarted.state().jobs["surgical"]
    assert job["review_outcome"] == "rejected"
    assert job["mutation_applied"] is False
    assert restarted.surgical_intent().estimated_count == 1
    second = restarted.start_surgical_update()
    assert second.job_id != first.job_id
    assert len(fake.edits) == 2
    history = restarted.state().jobs["surgical"]["history"]
    assert history[0]["job_id"] == first.job_id
    assert history[0]["review_outcome"] == "rejected"

    approved = LiveOrchestrator(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    approved.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=True)])
    again = LiveOrchestrator(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    assert again.surgical_intent().estimated_count == 0
    resumed = again.start_surgical_update()
    assert resumed.job_id == second.job_id
    assert len(fake.edits) == 2


def test_legacy_completed_without_outcome_is_ambiguous_until_annotated(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    state = orch.state()
    state.jobs["surgical"] = {
        "document_id": state.jobs["surgical"]["document_id"],
        "job_id": first.job_id,
        "profile_id": "profile-ns-swe-ii-payments",
        "section_id": "level_expectations",
        "status": "completed",
    }
    if "review:surgical" not in state.completed_steps:
        state.completed_steps.append("review:surgical")
    orch.store.save(state)

    resumed = LiveOrchestrator(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    migrated = resumed.state().jobs["surgical"]
    assert migrated["remote_job_status"] == "completed"
    assert migrated["review_outcome"] == "none"
    assert migrated["mutation_applied"] is False
    assert migrated["needs_review_annotation"] is True
    assert resumed.surgical_intent().estimated_count == 0
    with pytest.raises(SuperDocsError, match="review_outcome is missing"):
        resumed.start_surgical_update()
    assert len(fake.edits) == 1

    resumed.annotate_review("surgical", "rejected")
    annotated = resumed.state().jobs["surgical"]
    assert annotated["review_outcome"] == "rejected"
    assert annotated["mutation_applied"] is False
    assert annotated["job_id"] == first.job_id
    assert resumed.surgical_intent().estimated_count == 1
    second = resumed.start_surgical_update()
    assert second.job_id != first.job_id
    assert len(fake.edits) == 2
    history = resumed.state().jobs["surgical"]["history"]
    assert history[0]["job_id"] == first.job_id
    assert history[0]["review_outcome"] == "rejected"


def test_later_reviewed_jobs_infer_earlier_reviews_as_approved() -> None:
    state = LiveState(
        session_id="job-arch-live",
        completed_steps=["framework", "review:framework", "profile", "review:profile", "surgical", "review:surgical"],
        jobs={
            "framework": {"job_id": "job_offline_fw", "status": "completed"},
            "profile": {"job_id": "job_offline_pf", "status": "completed"},
            "surgical": {"job_id": "job_offline_sg", "status": "completed"},
        },
        operation_keys=["live-edit:framework", "live-edit:profile", "live-edit:surgical"],
    )
    assert prepare_jobs(state) is True
    assert state.jobs["framework"]["review_outcome"] == "approved"
    assert state.jobs["framework"]["mutation_applied"] is True
    assert state.jobs["profile"]["review_outcome"] == "approved"
    assert state.jobs["surgical"]["review_outcome"] == "none"
    assert state.jobs["surgical"]["mutation_applied"] is False
    assert reviewed_job_action(state.jobs["framework"]) == "done"
    assert reviewed_job_action(state.jobs["surgical"]) == "ambiguous"
    annotate_review(state, "surgical", "rejected")
    assert reviewed_job_action(state.jobs["surgical"]) == "new_edit"
    assert state.jobs["surgical"]["operation_key"] == "live-edit:surgical"


def test_failed_before_mutation_retries(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.start_surgical_update()
    state = orch.state()
    state.jobs["surgical"]["status"] = "failed"
    state.jobs["surgical"]["remote_job_status"] = "failed"
    state.jobs["surgical"]["review_outcome"] = "pending"
    state.jobs["surgical"]["mutation_applied"] = False
    orch.store.save(state)
    assert orch.surgical_intent().estimated_count == 1
    second = orch.start_surgical_update()
    assert second.job_id != first.job_id
    assert len(fake.edits) == 2
    assert orch.state().jobs["surgical"]["history"][0]["job_id"] == first.job_id
