"""Verification-gated domain apply and search resume. Offline only."""

from __future__ import annotations

from pathlib import Path

import pytest

from job_architecture.graph import SECTION_LEVEL_EXPECTATIONS
from job_architecture.live.docxgen import markdown_to_docx
from job_architecture.live.instructions import surgical_update_plan
from job_architecture.live.preservation import extract_docx_text
from job_architecture.superdocs.errors import SuperDocsError
from job_architecture.superdocs.models import JobSnapshot, ReviewDecision

from tests.live_fake import FakeProtocolClient
from tests.test_live_orchestration import _orchestrator


def _approve_surgical(orch):
    orch.start_surgical_update()
    return orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=True)])


def _write_verified_export(orch, tmp_path: Path) -> Path:
    profile, _old, _new, _plan = surgical_update_plan(orch.framework, orch.subset)
    filled = tmp_path / "artifacts" / f"{profile.id}.docx"
    text = extract_docx_text(filled)
    fragment = str(orch.state().preservation.get("expected_after_fragment") or "")
    if fragment and fragment.lower() not in text.lower():
        text = f"{text}\n{fragment}"
    destination = tmp_path / "exports" / "profile.docx"
    markdown_to_docx(text, destination, title="verified-export")
    structure = orch.verify_profile_structure(destination)
    assert structure["ok"], structure["violations"]
    preservation = orch.verify_export(destination)
    assert preservation["ok"], preservation
    return destination


def test_domain_apply_refuses_before_verification(tmp_path: Path) -> None:
    orch, _ = _orchestrator(tmp_path)
    _profile, old, planned, _plan = surgical_update_plan(orch.framework, orch.subset)
    _approve_surgical(orch)
    with pytest.raises(SuperDocsError, match="verification"):
        orch.finalize_domain_apply()
    assert orch.framework.level(old.id).version == old.version
    assert orch.state().jobs["surgical"]["domain_applied"] is False
    assert planned.version == old.version + 1


def test_domain_apply_succeeds_after_approved_mutation_and_verification(tmp_path: Path) -> None:
    orch, _ = _orchestrator(tmp_path)
    _profile, old, planned, _plan = surgical_update_plan(orch.framework, orch.subset)
    _approve_surgical(orch)
    assert orch.framework.level(old.id).version == old.version
    _write_verified_export(orch, tmp_path)
    result = orch.finalize_domain_apply()
    assert result["ok"] is True
    assert result["idempotent"] is False
    assert orch.state().jobs["surgical"]["domain_applied"] is True
    assert orch.framework.level(old.id).version == planned.version
    edge = next(
        item
        for item in orch.framework.dependency_graph.for_profile(_profile.id)
        if item.target_section == SECTION_LEVEL_EXPECTATIONS
    )
    assert edge.source_version == planned.version


def test_dependency_version_advances_only_at_domain_apply(tmp_path: Path) -> None:
    orch, _ = _orchestrator(tmp_path)
    _profile, old, planned, _plan = surgical_update_plan(orch.framework, orch.subset)
    orch.start_surgical_update()
    assert orch.framework.level(old.id).version == old.version
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=True)])
    assert orch.framework.level(old.id).version == old.version
    assert orch.state().jobs["surgical"]["mutation_applied"] is True
    _write_verified_export(orch, tmp_path)
    orch.finalize_domain_apply()
    assert orch.framework.level(old.id).version == planned.version


def test_repeated_finalize_is_idempotent(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    _profile, old, planned, _plan = surgical_update_plan(orch.framework, orch.subset)
    _approve_surgical(orch)
    _write_verified_export(orch, tmp_path)
    first = orch.finalize_domain_apply()
    second = orch.finalize_domain_apply()
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert orch.framework.level(old.id).version == planned.version
    assert orch.state().jobs["surgical"]["domain_applied"] is True
    history = orch.state().jobs["surgical"].get("history") or []
    assert orch.state().jobs["surgical"]["mutation_applied"] is True
    restarted = type(orch)(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    third = restarted.finalize_domain_apply()
    assert third["idempotent"] is True
    assert restarted.framework.level(old.id).version == planned.version
    assert len(fake.edits) == 1
    assert history == restarted.state().jobs["surgical"].get("history")


def test_rejected_attempts_can_never_be_domain_applied(tmp_path: Path) -> None:
    orch, _ = _orchestrator(tmp_path)
    _profile, old, _planned, _plan = surgical_update_plan(orch.framework, orch.subset)
    orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=False)])
    _write_verified_export(orch, tmp_path)
    with pytest.raises(SuperDocsError, match="rejected"):
        orch.finalize_domain_apply()
    assert orch.framework.level(old.id).version == old.version
    assert orch.state().jobs["surgical"]["domain_applied"] is False
    orch.start_surgical_update()
    orch.submit_decisions("surgical", [ReviewDecision(change_id="ch_1", approved=True)])
    history = orch.state().jobs["surgical"]["history"]
    assert history[0]["review_outcome"] == "rejected"
    assert history[0]["domain_applied"] is False
    _write_verified_export(orch, tmp_path)
    orch.finalize_domain_apply()
    kept = orch.state().jobs["surgical"]["history"]
    assert kept[0]["review_outcome"] == "rejected"
    assert kept[0]["domain_applied"] is False
    assert orch.state().jobs["surgical"]["domain_applied"] is True


def _processing_snapshot(job_id: str, session_id: str) -> JobSnapshot:
    return JobSnapshot(
        job_id=job_id,
        session_id=session_id,
        raw_status="processing",
        status="processing",
        progress=40,
        error=None,
        pending_changes=(),
        awaiting_kind=None,
        result=None,
        metadata={},
        raw={},
    )


def test_existing_processing_search_resumes_without_another_post(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    fake.jobs["job_seed_search"] = _processing_snapshot("job_seed_search", orch.subset.session_id)
    state = orch.state()
    state.jobs["search"] = {
        "job_id": "job_seed_search",
        "status": "processing",
        "remote_job_status": "processing",
        "query": orch.subset.search_query,
        "verified": False,
    }
    orch.store.save(state)
    intent = orch.search_intent()
    assert intent.estimated_count == 0
    outcome = orch.poll_search()
    assert fake.searches == []
    assert outcome["posted"] is False
    assert outcome["verified"] is True
    assert outcome["snapshot"].status == "completed"
    assert orch.state().jobs["search"]["job_id"] == "job_seed_search"
    assert orch.state().jobs["search"]["verified"] is True


def test_completed_search_is_not_duplicated(tmp_path: Path) -> None:
    orch, fake = _orchestrator(tmp_path)
    first = orch.poll_search()
    assert first["posted"] is True
    assert len(fake.searches) == 1
    second = orch.poll_search()
    assert second["posted"] is False
    assert len(fake.searches) == 1
    assert second["accepted"].handle.job_id == first["accepted"].handle.job_id
    assert orch.state().jobs["search"]["verified"] is True
    restarted = type(orch)(fake, orch.store, artifacts_dir=tmp_path / "artifacts")
    third = restarted.poll_search()
    assert third["posted"] is False
    assert len(fake.searches) == 1
    assert restarted.state().jobs["search"]["verified"] is True
