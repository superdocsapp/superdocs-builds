"""Fake clients for orchestrator tests — same discipline as zoom-app's
FakeSuperDocsClient: realistic canned responses, no network, no mocks
library. Each fake records what it was asked so tests can assert on the
exact request arguments (the identity invariants live there).
"""

from __future__ import annotations

from app.superdocs.schemas import (
    ChatAsyncResponse,
    ExportResult,
    JobMetadata,
    JobResult,
    JobStatusResponse,
    PendingChange,
    UploadResponse,
)


class FakeSuperDocsClient:
    """Configurable SuperDocs fake.

    - `approve_succeeds=True`: batch/individual approve advances the job to
      `completed` (the native HITL happy path).
    - `approve_succeeds=False`: the job stays `awaiting_approval` forever —
      reproduces the known zoom-app finding that the live approve endpoint
      returned 200 but never advanced the job. The workflow must enter
      BLOCKED, never pretend approval happened.
    """

    def __init__(
        self,
        *,
        approve_succeeds: bool = True,
        pending_changes: list[PendingChange] | None = None,
        complete_immediately: bool = False,
    ) -> None:
        # complete_immediately: the review job settles at `completed` with
        # zero pending changes — reproduces the real no-op review outcome.
        self.complete_immediately = complete_immediately
        self.approve_succeeds = approve_succeeds
        # Live-verified pending-change shape (2026-08): before/after text
        # arrives as old_html/new_html (never html_before/html_after), and
        # each change carries BOTH chunk_id and change_id (distinct values;
        # approval payloads use change_id).
        self._pending = pending_changes or [
            PendingChange(
                chunk_id="c1",
                change_id="chg1",
                operation="edit",
                old_html="<p>Thier report was submitted.</p>",
                new_html="<p>Their report was submitted.</p>",
            ),
            PendingChange(
                chunk_id="c2",
                change_id="chg2",
                operation="edit",
                old_html="<p>He go to school every day.</p>",
                new_html="<p>He goes to school every day.</p>",
            ),
        ]
        # The job only reaches `completed` after an approval call lands.
        # Before that it is awaiting_approval with pending changes — the
        # same lifecycle the real API follows (chat -> awaiting_approval ->
        # approve -> completed).
        self._approval_submitted = False
        self.upload_calls: list[dict] = []
        self.chat_calls: list[dict] = []
        self.approve_batch_calls: list[dict] = []
        self.approve_calls: list[dict] = []
        self.export_calls: list[dict] = []

    async def aclose(self) -> None:
        pass

    async def upload_base64(self, *, file_base64, filename, session_id, return_html=True):
        self.upload_calls.append(
            {"file_base64": file_base64, "filename": filename, "session_id": session_id}
        )
        return UploadResponse(session_id=session_id, html="", chunks_count=2)

    async def chat_async(
        self,
        *,
        message,
        session_id,
        approval_mode="auto",
        model_tier=None,
        thinking_depth=None,
    ):
        self.chat_calls.append(
            {
                "message": message,
                "session_id": session_id,
                "approval_mode": approval_mode,
                "model_tier": model_tier,
                "thinking_depth": thinking_depth,
            }
        )
        return ChatAsyncResponse(job_id="job1", session_id=session_id)

    async def get_job(self, job_id):
        if self.complete_immediately:
            return JobStatusResponse(
                job_id=job_id,
                status="completed",
                metadata=JobMetadata(pending_changes=[]),
                result=JobResult(document_changes=None, response="no changes made"),
            )
        if self._approval_submitted and self.approve_succeeds:
            return JobStatusResponse(
                job_id=job_id,
                status="completed",
                metadata=JobMetadata(pending_changes=[]),
                result=JobResult(
                    document_changes=None,
                    response="review done",
                ),
            )
        return JobStatusResponse(
            job_id=job_id,
            status="awaiting_approval",
            metadata=JobMetadata(pending_changes=self._pending),
        )

    async def approve_batch(self, *, session_id, job_id, approved, changes):
        self.approve_batch_calls.append(
            {"session_id": session_id, "job_id": job_id, "approved": approved, "changes": changes}
        )
        self._approval_submitted = True
        return {"status": "ok", "batch_complete": self.approve_succeeds}

    async def approve(self, *, session_id, job_id, approved=True, chunk_id=None):
        self.approve_calls.append(
            {"session_id": session_id, "job_id": job_id, "approved": approved, "chunk_id": chunk_id}
        )
        self._approval_submitted = True
        return {"status": "ok", "batch_complete": self.approve_succeeds}

    async def export(self, *, session_id, format="docx"):
        self.export_calls.append({"session_id": session_id, "format": format})
        return ExportResult(
            content=b"PK-reviewed-docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            warnings=[],
        )


class FakeGoogleClassroomClient:
    """Canned Classroom responses. `submission` defaults to a submission
    carrying a Drive attachment; tests override for edge cases."""

    def __init__(self, submission: dict | None = None, student_name: str = "Student One") -> None:
        # Realistic shape per the official API contract: attachments nest
        # under assignmentSubmission (not top-level).
        self.submission = submission or {
            "id": "s1",
            "userId": "u1",
            "state": "TURNED_IN",
            "courseWorkId": "w1",
            "courseWorkType": "ASSIGNMENT",
            "assignmentSubmission": {
                "attachments": [
                    {"driveFile": {"id": "d1", "title": "student-essay.docx", "alternateLink": "https://drive.google.com/file/d/d1/view"}}
                ]
            },
        }
        self.student_name = student_name
        self.modify_attachments_calls: list[dict] = []
        self.return_calls: list[dict] = []
        self.get_calls: list[dict] = []

    async def aclose(self) -> None:
        pass

    async def list_courses(self, access_token):
        return [{"id": "c1", "name": "English 101", "section": "A"}]

    async def list_coursework(self, access_token, course_id):
        return [{"id": "w1", "title": "Task 2B Feedback Demo", "state": "PUBLISHED"}]

    async def list_submissions(self, access_token, course_id, coursework_id):
        return [self.submission]

    async def get_submission(self, access_token, course_id, coursework_id, submission_id):
        self.get_calls.append(
            {"course_id": course_id, "coursework_id": coursework_id, "submission_id": submission_id}
        )
        return self.submission

    async def modify_attachments(
        self, access_token, course_id, coursework_id, submission_id, add_attachments
    ):
        self.modify_attachments_calls.append(
            {
                "course_id": course_id,
                "coursework_id": coursework_id,
                "submission_id": submission_id,
                "add_attachments": add_attachments,
            }
        )
        self.submission["assignmentSubmission"]["attachments"] = (
            self.submission["assignmentSubmission"]["attachments"] + add_attachments
        )
        return self.submission

    async def return_submission(self, access_token, course_id, coursework_id, submission_id):
        self.return_calls.append(
            {"course_id": course_id, "coursework_id": coursework_id, "submission_id": submission_id}
        )
        self.submission["state"] = "RETURNED"
        return self.submission


class FakeGoogleDriveClient:
    def __init__(self) -> None:
        self.download_calls: list[dict] = []
        self.upload_calls: list[dict] = []

    async def aclose(self) -> None:
        pass

    async def get_file_metadata(self, access_token, file_id):
        return {
            "id": file_id,
            "name": "student-essay.docx",
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }

    async def download_file(self, access_token, file_id, mime_type=None):
        self.download_calls.append({"file_id": file_id, "mime_type": mime_type})
        return b"original-docx-bytes"

    async def upload_file(self, access_token, name, content, mime_type):
        self.upload_calls.append({"name": name, "content": content, "mime_type": mime_type})
        return {"id": "r1", "name": name}
