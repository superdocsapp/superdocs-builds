"""ReviewWorkflow tests — the full happy path against fake clients."""

import asyncio

from app.workflow.models import WorkflowData, WorkflowState
from app.workflow.orchestrator import ReviewWorkflow
from tests.fakes import FakeGoogleClassroomClient, FakeGoogleDriveClient, FakeSuperDocsClient


async def _token_provider():
    return "test-access-token"


def _workflow(fake_superdocs=None, fake_classroom=None, fake_drive=None) -> ReviewWorkflow:
    data = WorkflowData(
        workflow_id="wf1",
        course_id="c1",
        course_name="English 101",
        coursework_id="w1",
        assignment_title="Task 2B Feedback Demo",
        submission_id="s1",
    )
    return ReviewWorkflow(
        data,
        fake_classroom or FakeGoogleClassroomClient(),
        fake_drive or FakeGoogleDriveClient(),
        fake_superdocs or FakeSuperDocsClient(approve_succeeds=True),
        _token_provider,
        job_poll_deadline_seconds=10.0,
        approval_poll_deadline_seconds=2.0,
        poll_interval_seconds=0.01,
    )


def _run_through_awaiting_approval(wf) -> WorkflowData:
    """Runs steps 1-3: retrieve -> upload -> review, ending at
    AWAITING_APPROVAL with pending changes."""
    data = asyncio.run(wf.retrieve_submission())
    assert data.state == WorkflowState.DOCUMENT_RETRIEVED
    assert data.original_drive_file_id == "d1"
    assert data.original_filename == "student-essay.docx"

    data = asyncio.run(wf.upload_to_superdocs())
    assert data.state == WorkflowState.SUPERDOCS_UPLOADED
    assert data.superdocs_session_id.startswith("classroom-")

    data = asyncio.run(wf.start_review("Review for grammar and clarity."))
    assert data.state == WorkflowState.AWAITING_APPROVAL
    assert len(data.pending_changes) == 2
    assert data.approval_mode_used == "ask_every_time"
    return data


def test_full_happy_path_end_to_end():
    wf = _workflow()
    _run_through_awaiting_approval(wf)

    # Teacher decides: approve c1, reject c2.
    data = asyncio.run(wf.decide("c1", "approved"))
    assert data.review_decisions == {"c1": "approved"}
    data = asyncio.run(wf.decide("c2", "rejected"))
    assert data.all_decided()

    # Native approval advances the job to completed.
    data = asyncio.run(wf.submit_approval())
    assert data.state == WorkflowState.APPROVAL_COMPLETE
    assert data.approval_mode_used == "ask_every_time"

    # Export (gated on APPROVAL_COMPLETE).
    data = asyncio.run(wf.export_reviewed())
    assert data.state == WorkflowState.EXPORTED

    # Drive upload.
    data = asyncio.run(wf.upload_to_drive())
    assert data.state == WorkflowState.DRIVE_UPLOADED
    assert data.reviewed_drive_file_id == "r1"

    # Attach to the SAME submission.
    data = asyncio.run(wf.attach_to_submission())
    assert data.state == WorkflowState.ATTACHED

    # Return.
    data = asyncio.run(wf.return_submission())
    assert data.state == WorkflowState.RETURNED

    # Verify — the reviewed file must be on the submission.
    data = asyncio.run(wf.verify())
    assert data.state == WorkflowState.VERIFIED
    assert data.verification["all_passed"] is True
    assert data.verification["checks"]["reviewed_file_attached"] is True


def test_start_review_uses_ask_every_time_mode():
    fake = FakeSuperDocsClient(approve_succeeds=True)
    wf = _workflow(fake_superdocs=fake)
    _run_through_awaiting_approval(wf)
    assert fake.chat_calls[0]["approval_mode"] == "ask_every_time"


def test_review_instruction_preserved():
    fake = FakeSuperDocsClient(approve_succeeds=True)
    wf = _workflow(fake_superdocs=fake)
    _run_through_awaiting_approval(wf)
    assert "Review for grammar and clarity." in fake.chat_calls[0]["message"]


def test_extracts_drive_file_from_assignment_submission():
    """Regression: the real Classroom API nests attachments under
    assignmentSubmission.attachments — extraction must read the REAL
    location, not the (nonexistent) top-level key."""
    classroom = FakeGoogleClassroomClient(
        submission={
            "id": "s1",
            "userId": "u1",
            "state": "TURNED_IN",
            "courseWorkType": "ASSIGNMENT",
            "assignmentSubmission": {
                "attachments": [
                    {"driveFile": {"id": "d1", "title": "student-essay.docx"}}
                ]
            },
        }
    )
    wf = _workflow(fake_classroom=classroom)
    data = asyncio.run(wf.retrieve_submission())
    assert data.state == WorkflowState.DOCUMENT_RETRIEVED
    assert data.original_drive_file_id == "d1"
    assert data.original_filename == "student-essay.docx"


def test_link_only_attachment_fails_honestly():
    """A submission whose only attachment is a link (no driveFile) must
    fail with the clear message — never substitute another file."""
    classroom = FakeGoogleClassroomClient(
        submission={
            "id": "s1",
            "userId": "u1",
            "state": "TURNED_IN",
            "courseWorkType": "ASSIGNMENT",
            "assignmentSubmission": {
                "attachments": [{"link": {"url": "https://example.com/essay"}}]
            },
        }
    )
    wf = _workflow(fake_classroom=classroom)
    data = asyncio.run(wf.retrieve_submission())
    assert data.state == WorkflowState.ERROR
    assert "no Drive file attachment" in data.error


def test_submission_without_drive_attachment_fails_honestly():
    classroom = FakeGoogleClassroomClient(
        submission={
            "id": "s1",
            "userId": "u1",
            "state": "TURNED_IN",
            "courseWorkType": "ASSIGNMENT",
            "assignmentSubmission": {"attachments": []},
        }
    )
    wf = _workflow(fake_classroom=classroom)
    data = asyncio.run(wf.retrieve_submission())
    assert data.state == WorkflowState.ERROR
    assert "no Drive file attachment" in data.error


def test_export_blocked_when_approval_never_happened():
    wf = _workflow()
    _run_through_awaiting_approval(wf)
    data = asyncio.run(wf.export_reviewed())
    assert data.state == WorkflowState.ERROR
    assert "requires APPROVAL_COMPLETE" in data.error


def test_identity_guard_rejects_wrong_ids():
    """_guard_identity must refuse a caller that tries to substitute a
    different submission for the one the workflow was bound to."""
    from app.workflow.orchestrator import WorkflowError

    wf = _workflow()
    try:
        wf._guard_identity(course_id="c1", coursework_id="w1", submission_id="OTHER")
    except WorkflowError as exc:
        assert "Refusing to operate on a different submission" in str(exc)
        return
    raise AssertionError("identity guard did not fire for a wrong submission id")


def test_classroom_called_with_exact_stored_ids():
    """The Classroom client receives precisely the workflow's stored
    course/coursework/submission ids for get, modifyAttachments, return —
    identity by ID, never by filename or search."""
    classroom = FakeGoogleClassroomClient()
    wf = _workflow(fake_classroom=classroom)
    _run_through_awaiting_approval(wf)

    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    asyncio.run(wf.submit_approval())
    asyncio.run(wf.export_reviewed())
    asyncio.run(wf.upload_to_drive())
    asyncio.run(wf.attach_to_submission())
    asyncio.run(wf.return_submission())
    asyncio.run(wf.verify())

    for call in classroom.modify_attachments_calls + classroom.return_calls:
        assert call["course_id"] == "c1"
        assert call["coursework_id"] == "w1"
        assert call["submission_id"] == "s1"
    assert classroom.modify_attachments_calls[0]["add_attachments"] == [
        {"driveFile": {"id": "r1"}}
    ]
