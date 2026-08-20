"""Native HITL gating tests — the strongest acceptance criterion.

The teacher's decisions must genuinely control what is exported, and a
SuperDocs approval that does not advance the job must produce BLOCKED, not
a silent workaround.
"""

import asyncio

from app.workflow.models import WorkflowState
from app.workflow.orchestrator import ReviewWorkflow
from tests.fakes import FakeGoogleClassroomClient, FakeGoogleDriveClient, FakeSuperDocsClient
from tests.test_orchestrator import _run_through_awaiting_approval, _token_provider, _workflow


def _blocked_workflow() -> tuple[ReviewWorkflow, FakeSuperDocsClient]:
    """A workflow whose SuperDocs fake never advances past
    awaiting_approval after approval submission — reproduces the known
    live-API finding (approve returns 200, job stays awaiting_approval)."""
    fake = FakeSuperDocsClient(approve_succeeds=False)
    wf = _workflow(fake_superdocs=fake)
    _run_through_awaiting_approval(wf)
    return wf, fake


def test_teacher_must_decide_all_changes_before_submit():
    wf, _ = _blocked_workflow()
    asyncio.run(wf.decide("c1", "approved"))
    # c2 still pending.
    data = asyncio.run(wf.submit_approval())
    assert data.state == WorkflowState.ERROR
    assert "no teacher decision yet" in data.error


def test_all_changes_pending_blocks_export():
    wf, _ = _blocked_workflow()
    data = asyncio.run(wf.export_reviewed())
    assert data.state == WorkflowState.ERROR
    assert "requires APPROVAL_COMPLETE" in data.error


def test_approval_that_does_not_advance_job_enters_blocked():
    """The core honesty rule: approve returns 200 but the job never leaves
    awaiting_approval → BLOCKED. Never pretend approval happened."""
    wf, fake = _blocked_workflow()
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))

    data = asyncio.run(wf.submit_approval())
    assert data.state == WorkflowState.BLOCKED
    assert fake.approve_batch_calls, "batch approve must have been attempted"
    assert "did not advance" in data.blocker_reason


def test_blocked_state_records_exact_reason():
    wf, _ = _blocked_workflow()
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    data = asyncio.run(wf.submit_approval())
    assert data.state == WorkflowState.BLOCKED
    assert data.blocker_reason  # exact reason recorded, not "Something went wrong"
    assert data.review_decisions == {"c1": "approved", "c2": "rejected"}


def test_blocked_prevents_export():
    wf, _ = _blocked_workflow()
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    asyncio.run(wf.submit_approval())
    data = asyncio.run(wf.export_reviewed())
    assert data.state != WorkflowState.EXPORTED
    assert data.state == WorkflowState.BLOCKED


def test_completed_with_zero_changes_is_not_approval():
    """A review job that completes with zero proposed changes must NOT be
    presented as HITL approval — the workflow stops at REVIEW_GENERATED,
    export stays blocked. This pins the live no-op outcome honestly."""
    fake = FakeSuperDocsClient(complete_immediately=True)
    wf = _workflow(fake_superdocs=fake)
    asyncio.run(wf.retrieve_submission())
    asyncio.run(wf.upload_to_superdocs())
    data = asyncio.run(wf.start_review("Review for grammar."))
    assert data.state == WorkflowState.REVIEW_GENERATED
    assert "no proposed changes" in data.timeline[-1].detail
    data = asyncio.run(wf.export_reviewed())
    assert data.state != WorkflowState.EXPORTED
    assert "requires APPROVAL_COMPLETE" in data.error


def test_default_review_instruction_is_imperative_and_uncontaminated():
    """The default instruction must be the live-verified imperative form
    that produces real pending changes, and must explicitly demand
    replacement-only content: no 'Original:'/'Corrected:' labels, no
    'Changes made:'/'List of changes:' summaries, no commentary inside
    the replacement. (Live-traced: the earlier wording 'showing the
    original text and the corrected text' induced SuperDocs to embed
    annotations inside new_html.)"""
    from app.workflow.orchestrator import DEFAULT_REVIEW_INSTRUCTION

    assert "Edit this document to fix grammar" in DEFAULT_REVIEW_INSTRUCTION
    assert "propose the corrected replacement text only" in DEFAULT_REVIEW_INSTRUCTION
    assert "without labels such as 'Original:' or 'Corrected:'" in DEFAULT_REVIEW_INSTRUCTION
    assert "'Changes made:'" in DEFAULT_REVIEW_INSTRUCTION
    assert "'List of changes:'" in DEFAULT_REVIEW_INSTRUCTION
    assert "Any explanation must stay separate" in DEFAULT_REVIEW_INSTRUCTION


def test_pending_changes_surface_old_and_new_html():
    """Live-verified: pending before/after text arrives as old_html/
    new_html — the workflow must surface it under those names."""
    fake = FakeSuperDocsClient(approve_succeeds=True)
    wf = _workflow(fake_superdocs=fake)
    _run_through_awaiting_approval(wf)
    change = wf.data.pending_changes[0]
    assert change.old_html == "<p>Thier report was submitted.</p>"
    assert change.new_html == "<p>Their report was submitted.</p>"


def test_blocked_workflow_cannot_attach_or_return():
    """Classroom safety: a blocked workflow must never reach
    modifyAttachments or return — an unapproved document must never be
    attached to a student's submission."""
    from tests.fakes import FakeGoogleClassroomClient as GC

    classroom = GC()
    wf = _workflow(fake_classroom=classroom, fake_superdocs=FakeSuperDocsClient(approve_succeeds=False))
    _run_through_awaiting_approval(wf)
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    asyncio.run(wf.submit_approval())
    assert wf.data.state == WorkflowState.BLOCKED

    data = asyncio.run(wf.attach_to_submission())
    assert data.state != WorkflowState.ATTACHED
    data = asyncio.run(wf.return_submission())
    assert data.state != WorkflowState.RETURNED
    assert classroom.modify_attachments_calls == []
    assert classroom.return_calls == []


def test_blocked_never_falls_back_to_auto_mode():
    """The workflow must not silently re-run the edit with
    approval_mode=auto as a substitute for native approval."""
    wf, fake = _blocked_workflow()
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    asyncio.run(wf.submit_approval())
    for call in fake.chat_calls:
        assert call["approval_mode"] == "ask_every_time", (
            "a fallback chat call must never switch to auto approval"
        )


def test_batch_approve_submits_teacher_decisions_by_change_id():
    """The decisions sent to SuperDocs must use the current documented
    schema: {job_id, approved, changes: [{change_id, approved}]} — the
    nested identifier is change_id, never chunk_id (live-verified: they
    differ, and chunk_id-shaped approvals never advanced the job)."""
    fake = FakeSuperDocsClient(approve_succeeds=True)
    wf = _workflow(fake_superdocs=fake)
    _run_through_awaiting_approval(wf)
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    data = asyncio.run(wf.submit_approval())
    assert data.state == WorkflowState.APPROVAL_COMPLETE
    call = fake.approve_batch_calls[0]
    assert call["job_id"] == "job1"
    assert call["approved"] is True
    assert call["changes"] == [
        {"change_id": "chg1", "approved": True},
        {"change_id": "chg2", "approved": False},
    ]
    # chunk_id must never appear in the approval payload.
    assert all("chunk_id" not in c for c in call["changes"])


def test_approval_failure_surfaces_error_not_fallback():
    """If the documented approval call fails, the workflow records the
    error — it must not invent a substitute approval path."""
    fake = FakeSuperDocsClient(approve_succeeds=True)

    import httpx

    async def failing_batch(*, session_id, job_id, approved, changes):
        raise httpx.HTTPStatusError(
            "500", request=httpx.Request("POST", "https://api.superdocs.app/v1/chat/s/approve"),
            response=httpx.Response(500, request=httpx.Request("POST", "x")),
        )

    fake.approve_batch = failing_batch
    wf = _workflow(fake_superdocs=fake)
    _run_through_awaiting_approval(wf)
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))

    data = asyncio.run(wf.submit_approval())
    assert data.state == WorkflowState.ERROR
    assert "approval submission failed" in data.error
    assert fake.approve_calls == []  # no silent per-chunk fallback
