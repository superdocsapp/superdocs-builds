"""The critical same-submission invariant test.

Given submission ID S and original file O:
    1. retrieve S
    2. retrieve O
    3. create reviewed file R
    4. modifyAttachments(S, R)
    5. return(S)
    6. retrieve S again

Assert: S contains R. Not merely that R exists in Drive.
"""

import asyncio

from app.workflow.models import WorkflowState
from tests.fakes import FakeGoogleClassroomClient, FakeGoogleDriveClient, FakeSuperDocsClient
from tests.test_orchestrator import _run_through_awaiting_approval, _token_provider, _workflow


def test_reviewed_file_attached_to_same_submission():
    classroom = FakeGoogleClassroomClient()
    drive = FakeGoogleDriveClient()
    wf = _workflow(
        fake_classroom=classroom,
        fake_drive=drive,
        fake_superdocs=FakeSuperDocsClient(approve_succeeds=True),
    )

    _run_through_awaiting_approval(wf)
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    asyncio.run(wf.submit_approval())
    asyncio.run(wf.export_reviewed())
    asyncio.run(wf.upload_to_drive())
    asyncio.run(wf.attach_to_submission())
    asyncio.run(wf.return_submission())
    data = asyncio.run(wf.verify())

    assert data.state == WorkflowState.VERIFIED
    assert data.verification["checks"] == {
        "submission_exists": True,
        "submission_id_unchanged": True,
        "reviewed_file_attached": True,
    }

    # The submission now carries the reviewed file R alongside the original O.
    attached_ids = [
        a["driveFile"]["id"]
        for a in classroom.submission["assignmentSubmission"]["attachments"]
        if "driveFile" in a
    ]
    assert "r1" in attached_ids
    assert "d1" in attached_ids  # original still present, not replaced

    # Proof it is not an orphan: the reviewed file id exists only as an
    # attachment of S — the classroom client's record shows exactly one
    # modifyAttachments call, on submission s1.
    assert len(classroom.modify_attachments_calls) == 1
    assert classroom.modify_attachments_calls[0]["submission_id"] == "s1"


def test_verify_fails_when_reviewed_file_not_attached():
    """If the attachment did not land on the submission, verification must
    fail — the app may not claim success from the Drive side alone."""
    classroom = FakeGoogleClassroomClient()
    wf = _workflow(fake_classroom=classroom)
    _run_through_awaiting_approval(wf)
    asyncio.run(wf.decide("c1", "approved"))
    asyncio.run(wf.decide("c2", "rejected"))
    asyncio.run(wf.submit_approval())
    asyncio.run(wf.export_reviewed())
    asyncio.run(wf.upload_to_drive())

    # Sabotage: the reviewed file was never attached to the submission.
    wf.data.state = WorkflowState.ATTACHED  # state says attached...
    asyncio.run(wf.return_submission())
    data = asyncio.run(wf.verify())

    assert data.state == WorkflowState.ERROR
    assert data.verification["checks"]["reviewed_file_attached"] is False
    assert "do NOT claim the student received" in data.error


def test_original_file_identity_preserved_through_workflow():
    """original_drive_file_id comes from the submission attachment and is
    never swapped for the reviewed file id or anything else."""
    wf = _workflow()
    data = _run_through_awaiting_approval(wf)
    assert data.original_drive_file_id == "d1"
    assert data.original_drive_file_id != data.reviewed_drive_file_id
