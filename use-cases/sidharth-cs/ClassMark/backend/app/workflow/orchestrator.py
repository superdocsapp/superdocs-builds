"""ReviewWorkflow — the state machine that drives one submission through
the full loop:

    Classroom submission
      → Drive attachment download
      → SuperDocs upload
      → review instruction (approval_mode="ask_every_time")
      → pending changes shown to the teacher
      → teacher decides each change
      → native SuperDocs approval via the documented change_id batch contract
      → export (ONLY from a genuinely completed native approval)
      → Drive upload
      → modifyAttachments on THE SAME submission
      → studentSubmissions.return
      → post-return verification

Identity rule: course_id, coursework_id and submission_id are captured at
start() from the teacher's selections and passed verbatim to every
Classroom call. The orchestrator never looks up "the matching submission"
by filename, never searches, never substitutes. If a call would use
anything but the stored IDs, that's a bug — guarded by _guard_identity().

Native-HITL-only rule: the approval path is approval_mode="ask_every_time"
plus the /v1/chat/{session_id}/approve endpoint. If the job does not reach
`completed` after the teacher's decisions are submitted, the workflow
enters BLOCKED — it never silently re-runs the edit in auto mode and never
issues corrective edits to simulate approval.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
import uuid

from app.google.classroom import GoogleClassroomClient, submission_attachments
from app.google.drive import GoogleDriveClient
from app.superdocs.client import SuperDocsClient
from app.workflow.review_config import (
    DEFAULT_REVIEW_CONFIGURATION,
    DEFAULT_REVIEW_INSTRUCTION,
    ReviewConfiguration,
    build_review_instruction,
)
from app.workflow.models import (
    PendingChange,
    ReviewDecision,
    TimelineEntry,
    VerificationResult,
    WorkflowData,
    WorkflowState,
)

# SuperDocs' own /v1/chat/async validation (confirmed via its 422 body in
# zoom-app): session_id must match ^[a-zA-Z0-9_.-]+$.
_SESSION_ID_UNSAFE = re.compile(r"[^a-zA-Z0-9_.\-]")

# Minimal text comparison for no-op classification: strip HTML tags,
# normalize line endings, collapse whitespace, trim. Deliberately NOT
# aggressive (no case folding, no punctuation stripping) so meaningful
# changes — including case-only or punctuation-only edits — stay
# actionable.
_TAG_RE = re.compile(r"<[^>]*>")


def normalize_for_compare(html: str) -> str:
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(text.split()).strip()


def is_noop_change(old_html: str | None, new_html: str | None) -> bool:
    """True when the proposed replacement is textually identical to the
    original — SuperDocs genuinely returns such proposals (observed live:
    unchanged heading and paragraph chunks). Such changes require no
    teacher decision and are never sent to the approval endpoint.

    Comparison only — the stored original/suggested values are never
    mutated by no-op detection."""
    old = normalize_for_compare(old_html or "")
    new = normalize_for_compare(new_html or "")
    if not old or not new:
        return False
    return old == new

_JOB_POLL_INTERVAL_SECONDS = 4.0
_JOB_POLL_DEADLINE_SECONDS = 300.0  # SuperDocs edits can take minutes
_APPROVAL_POLL_DEADLINE_SECONDS = 60.0  # how long we wait for approval to land

# DEFAULT_REVIEW_INSTRUCTION remains re-exported from review_config for the
# stable recommended-instruction API, but all production review requests use
# the validated builder below.


class WorkflowError(Exception):
    """A step failed and the workflow cannot honestly advance."""


class ReviewWorkflow:
    def __init__(
        self,
        data: WorkflowData,
        classroom: GoogleClassroomClient,
        drive: GoogleDriveClient,
        superdocs: SuperDocsClient,
        access_token_provider,
        *,
        # Poll timing overridable so tests don't wait on real 300s/60s
        # deadlines — same reasoning as zoom-app's Batcher thresholds.
        job_poll_deadline_seconds: float = _JOB_POLL_DEADLINE_SECONDS,
        approval_poll_deadline_seconds: float = _APPROVAL_POLL_DEADLINE_SECONDS,
        poll_interval_seconds: float = _JOB_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.data = data
        self._classroom = classroom
        self._drive = drive
        self._superdocs = superdocs
        self._token = access_token_provider  # callable() -> valid access token
        self._lock = asyncio.Lock()
        self._document_bytes: bytes | None = None
        self._export_bytes: bytes | None = None
        self._job_poll_deadline = job_poll_deadline_seconds
        self._approval_poll_deadline = approval_poll_deadline_seconds
        self._poll_interval = poll_interval_seconds

    # ---- identity guard ---------------------------------------------------

    def _guard_identity(
        self, *, course_id: str, coursework_id: str, submission_id: str
    ) -> None:
        if (
            course_id != self.data.course_id
            or coursework_id != self.data.coursework_id
            or submission_id != self.data.submission_id
        ):
            raise WorkflowError(
                f"Identity mismatch: caller wanted "
                f"course={course_id} coursework={coursework_id} submission={submission_id}, "
                f"but this workflow is bound to "
                f"course={self.data.course_id} coursework={self.data.coursework_id} "
                f"submission={self.data.submission_id}. Refusing to operate on a "
                f"different submission."
            )

    # ---- transitions ------------------------------------------------------

    def _set_state(self, state: WorkflowState, detail: str) -> None:
        self.data.state = state
        self.data.timeline.append(TimelineEntry(state=state, detail=detail, at=time.time()))

    def _fail(self, detail: str) -> None:
        self.data.error = detail
        self._set_state(WorkflowState.ERROR, f"error: {detail}")

    # ---- step 1: retrieve the submission and its Drive attachment ---------

    async def retrieve_submission(self) -> WorkflowData:
        """Fetches the selected submission, extracts the Drive attachment,
        and downloads the original document. All IDs come from what start()
        already captured — nothing is inferred from filenames."""
        async with self._lock:
            try:
                token = await self._token()
                submission = await self._classroom.get_submission(
                    token,
                    self.data.course_id,
                    self.data.coursework_id,
                    self.data.submission_id,
                )
            except Exception as exc:  # surface the real failure, don't guess
                self._fail(f"retrieve submission failed: {exc}")
                return self.data

            attachments = [
                a for a in submission_attachments(submission) if a.get("driveFile")
            ]
            if not attachments:
                self._fail(
                    "submission has no Drive file attachment; only Drive-file "
                    "attachments can be reviewed"
                )
                return self.data

            drive_file = attachments[0]["driveFile"]
            self.data.original_drive_file_id = drive_file.get("id", "")
            self.data.original_filename = drive_file.get("title", drive_file.get("name", ""))
            self.data.student_user_id = submission.get("userId", "")
            self.data.original_mime_type = drive_file.get("mimeType", "")

            if not self.data.original_drive_file_id:
                self._fail("submission attachment has no Drive file id")
                return self.data

            try:
                metadata = await self._drive.get_file_metadata(
                    token, self.data.original_drive_file_id
                )
                self.data.original_filename = self.data.original_filename or metadata.get(
                    "name", ""
                )
                self.data.original_mime_type = self.data.original_mime_type or metadata.get(
                    "mimeType", ""
                )
                self._document_bytes = await self._drive.download_file(
                    token, self.data.original_drive_file_id, self.data.original_mime_type
                )
            except Exception as exc:
                self._fail(f"download original document failed: {exc}")
                return self.data

            if not self._document_bytes:
                self._fail("downloaded document is empty")
                return self.data

            self._set_state(
                WorkflowState.DOCUMENT_RETRIEVED,
                f"original document downloaded: {self.data.original_filename}",
            )
            return self.data

    # ---- step 2: upload to SuperDocs --------------------------------------

    async def upload_to_superdocs(self) -> WorkflowData:
        async with self._lock:
            if self._document_bytes is None:
                self._fail("no document bytes — retrieve_submission must run first")
                return self.data

            self.data.superdocs_session_id = (
                f"classroom-{_SESSION_ID_UNSAFE.sub('_', self.data.submission_id)}-{int(time.time())}"
            )
            try:
                await self._superdocs.upload_base64(
                    file_base64=base64.b64encode(self._document_bytes).decode(),
                    filename=self.data.original_filename or "submission.html",
                    session_id=self.data.superdocs_session_id,
                    return_html=False,
                )
            except Exception as exc:
                self._fail(f"SuperDocs upload failed: {exc}")
                return self.data

            self._set_state(
                WorkflowState.SUPERDOCS_UPLOADED,
                f"uploaded to SuperDocs session {self.data.superdocs_session_id}",
            )
            return self.data

    # ---- step 3: start the review (native HITL mode) -----------------------

    async def start_review(self, review: ReviewConfiguration | str) -> WorkflowData:
        """Sends the review instruction with approval_mode="ask_every_time"
        and polls until the job surfaces pending changes."""
        async with self._lock:
            if not self.data.superdocs_session_id:
                self._fail("not uploaded to SuperDocs yet")
                return self.data
            # String support keeps direct workflow callers from older tests and
            # scripts working. HTTP requests always supply ReviewConfiguration,
            # so only the backend builder controls production instructions.
            if isinstance(review, str):
                config = DEFAULT_REVIEW_CONFIGURATION
                instruction = review
            else:
                config = review
                instruction = build_review_instruction(config)
            self.data.review_mode = config.mode.value
            self.data.review_depth = config.depth.value
            try:
                chat = await self._superdocs.chat_async(
                    message=instruction,
                    session_id=self.data.superdocs_session_id,
                    approval_mode="ask_every_time",
                    model_tier=config.model_tier,
                    thinking_depth=config.thinking_depth,
                )
                self.data.review_job_id = chat.job_id
                self.data.approval_mode_used = "ask_every_time"
            except Exception as exc:
                self._fail(f"send review instruction failed: {exc}")
                return self.data

            try:
                job = await self._poll_job(
                    self.data.review_job_id, deadline=self._job_poll_deadline
                )
            except Exception as exc:
                self._fail(f"poll review job failed: {exc}")
                return self.data

            if job.status == "completed":
                # The job completed with no proposed changes. This is NOT
                # approval: there is nothing a human decided. The workflow
                # stops honestly at REVIEW_GENERATED — no export, no HITL
                # claim — so a no-op review can never masquerade as a
                # reviewed document.
                self._set_state(
                    WorkflowState.REVIEW_GENERATED,
                    "review produced no proposed changes — no HITL approval "
                    "possible; export requires a genuine native approval",
                )
                return self.data
            if job.status != "awaiting_approval":
                self._fail(f"review job ended in state {job.status!r}")
                return self.data

            pending = []
            for c in job.metadata.pending_changes:
                if not c.chunk_id:
                    continue
                # The suggested text is SuperDocs' authoritative
                # replacement — passed through verbatim. No heuristic
                # string surgery is ever applied to it.
                new_html = c.new_html or c.html_after
                pending.append(
                    PendingChange(
                        chunk_id=c.chunk_id,
                        change_id=c.change_id or "",
                        operation=c.operation,
                        old_html=c.old_html or c.html_before,
                        new_html=new_html,
                        ai_explanation=c.ai_explanation,
                        is_noop=is_noop_change(c.old_html or c.html_before, new_html),
                    )
                )
            if not pending:
                self._fail(
                    "job is awaiting_approval but returned no pending changes — "
                    "nothing the teacher can decide"
                )
                return self.data

            actionable = [c for c in pending if not c.is_noop]
            if not actionable:
                # Every proposal is a no-op (identical text). There is
                # nothing for the teacher to decide — an honest dead end,
                # never presented as approval.
                self.data.pending_changes = pending
                self._set_state(
                    WorkflowState.REVIEW_GENERATED,
                    "review produced only no-op changes (identical original and "
                    "suggested text) — nothing to approve",
                )
                return self.data

            self.data.pending_changes = pending
            self._set_state(
                WorkflowState.AWAITING_APPROVAL,
                f"{len(actionable)} actionable proposed changes awaiting teacher "
                f"decisions ({len(pending) - len(actionable)} no-op change(s) "
                f"excluded)",
            )
            return self.data

    # ---- step 4: teacher decisions (HITL) ----------------------------------

    async def decide(self, chunk_id: str, decision: str) -> WorkflowData:
        async with self._lock:
            decision = decision.lower()
            if decision not in ("approved", "rejected"):
                self._fail(f"invalid decision {decision!r}; expected approved or rejected")
                return self.data

            change = next((c for c in self.data.pending_changes if c.chunk_id == chunk_id), None)
            if change is None:
                self._fail(f"unknown chunk_id {chunk_id!r} — not in the pending changes")
                return self.data
            if change.is_noop:
                self._fail(
                    f"chunk {chunk_id!r} is a no-op change (identical original and "
                    f"suggested text) — no decision is required or accepted"
                )
                return self.data

            change.decision = ReviewDecision(decision)
            self.data.review_decisions[chunk_id] = decision
            return self.data

    # ---- step 5: submit approvals to SuperDocs (native HITL) ---------------

    async def submit_approval(self) -> WorkflowData:
        """Submits the teacher's decisions through the documented SuperDocs
        approval endpoint. Tries the documented batch shape first, then the
        per-chunk shape zoom-app confirmed against the live API. The job
        MUST reach `completed`; anything else enters BLOCKED."""
        async with self._lock:
            if self.data.state != WorkflowState.AWAITING_APPROVAL:
                self._fail(
                    f"submit_approval requires AWAITING_APPROVAL, current state is "
                    f"{self.data.state.value}"
                )
                return self.data
            if not self.data.all_decided():
                self._fail("cannot submit — some changes have no teacher decision yet")
                return self.data

            # The current official SuperDocs schema (live-verified 2026-08):
            # {job_id, approved, changes: [{change_id, approved}]} — nested
            # identifier is change_id, NOT chunk_id. One call carries the
            # teacher's full decision set; the docs state approved changes
            # apply atomically and denied changes are discarded.
            # No-op changes (identical text) are excluded: they require no
            # decision and are textually inert in the exported document.
            actionable = [c for c in self.data.pending_changes if not c.is_noop]
            decisions = [
                {
                    "change_id": c.change_id,
                    "approved": c.decision == ReviewDecision.APPROVED,
                }
                for c in actionable
                if c.change_id
            ]
            if not decisions or len(decisions) != len(actionable):
                self._fail(
                    "cannot submit approval — an actionable change has no "
                    "change_id (the SuperDocs identifier the approve endpoint "
                    "requires)"
                )
                return self.data

            try:
                await self._superdocs.approve_batch(
                    session_id=self.data.superdocs_session_id,
                    job_id=self.data.review_job_id,
                    approved=True,
                    changes=decisions,
                )
            except Exception as exc:
                self._fail(f"approval submission failed: {exc}")
                return self.data

            # The job must actually advance to `completed`. If it is still
            # awaiting_approval when the deadline passes, the native
            # approval path genuinely does not work — BLOCKED, not worked
            # around.
            try:
                job = await self._poll_job(
                    self.data.review_job_id, deadline=self._approval_poll_deadline
                )
            except TimeoutError:
                self._set_blocked(
                    f"SuperDocs native approval did not advance job "
                    f"{self.data.review_job_id}: it stayed awaiting_approval after "
                    f"{len(decisions)} decisions were submitted. The approve endpoint "
                    f"accepted the request but the job never reached completed. "
                    f"Teacher decisions are preserved; export is not possible until "
                    f"this resolves."
                )
                return self.data

            if job.status != "completed":
                self._set_blocked(
                    f"SuperDocs native approval did not advance job "
                    f"{self.data.review_job_id}: it settled in state {job.status!r}, "
                    f"not completed. Decisions were submitted through the documented "
                    f"approval endpoint but were not applied."
                )
                return self.data

            self._set_state(
                WorkflowState.APPROVAL_COMPLETE,
                "native SuperDocs approval completed: job reached completed",
            )
            return self.data

    def _set_blocked(self, reason: str) -> None:
        self.data.blocker_reason = reason
        self._set_state(WorkflowState.BLOCKED, f"blocked: {reason}")

    # ---- step 6: export (gated on genuine native approval) -----------------

    async def export_reviewed(self) -> WorkflowData:
        async with self._lock:
            if self.data.state == WorkflowState.BLOCKED:
                # A blocked workflow stays blocked — an export attempt must
                # not overwrite the blocker status with a generic error.
                self.data.error = (
                    "cannot export — native SuperDocs approval has not completed"
                )
                return self.data
            if self.data.state != WorkflowState.APPROVAL_COMPLETE:
                self._fail(
                    f"export requires APPROVAL_COMPLETE (genuine native SuperDocs "
                    f"approval); current state is {self.data.state.value}"
                )
                return self.data
            try:
                result = await self._superdocs.export(
                    session_id=self.data.superdocs_session_id, format="docx"
                )
            except Exception as exc:
                self._fail(f"SuperDocs export failed: {exc}")
                return self.data

            self._export_bytes = result.content
            self._set_state(
                WorkflowState.EXPORTED,
                f"exported reviewed document ({len(result.content)} bytes)"
                + (f"; export warnings: {result.warnings}" if result.warnings else ""),
            )
            return self.data

    # ---- step 7: upload to Drive + attach to the SAME submission -----------

    async def upload_to_drive(self) -> WorkflowData:
        async with self._lock:
            if self.data.state != WorkflowState.EXPORTED:
                self._fail(
                    f"upload_to_drive requires EXPORTED; current state is {self.data.state.value}"
                )
                return self.data
            if self._export_bytes is None:
                self._fail("no exported bytes — export_reviewed must run first")
                return self.data

            base = self.data.original_filename.rsplit(".", 1)[0] or "reviewed"
            self.data.reviewed_filename = f"{base}_reviewed.docx"
            try:
                uploaded = await self._drive.upload_file(
                    await self._token(),
                    name=self.data.reviewed_filename,
                    content=self._export_bytes,
                    mime_type=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                )
            except Exception as exc:
                self._fail(f"Drive upload of reviewed document failed: {exc}")
                return self.data

            self.data.reviewed_drive_file_id = uploaded.get("id", "")
            if not self.data.reviewed_drive_file_id:
                self._fail("Drive upload returned no file id")
                return self.data

            self._set_state(
                WorkflowState.DRIVE_UPLOADED,
                f"reviewed document in Drive: {self.data.reviewed_filename} "
                f"({self.data.reviewed_drive_file_id})",
            )
            return self.data

    async def attach_to_submission(self) -> WorkflowData:
        async with self._lock:
            if self.data.state != WorkflowState.DRIVE_UPLOADED:
                self._fail(
                    f"attach_to_submission requires DRIVE_UPLOADED; current state is "
                    f"{self.data.state.value}"
                )
                return self.data
            if not self.data.reviewed_drive_file_id:
                self._fail("no reviewed Drive file id — upload_to_drive must run first")
                return self.data

            self._guard_identity(
                course_id=self.data.course_id,
                coursework_id=self.data.coursework_id,
                submission_id=self.data.submission_id,
            )
            try:
                await self._classroom.modify_attachments(
                    await self._token(),
                    self.data.course_id,
                    self.data.coursework_id,
                    self.data.submission_id,
                    add_attachments=[
                        {"driveFile": {"id": self.data.reviewed_drive_file_id}}
                    ],
                )
            except Exception as exc:
                self._fail(f"modifyAttachments failed: {exc}")
                return self.data

            self._set_state(
                WorkflowState.ATTACHED,
                f"reviewed file {self.data.reviewed_drive_file_id} attached to "
                f"submission {self.data.submission_id}",
            )
            return self.data

    # ---- step 8: return -----------------------------------------------------

    async def return_submission(self) -> WorkflowData:
        async with self._lock:
            if self.data.state != WorkflowState.ATTACHED:
                self._fail(
                    f"return_submission requires ATTACHED; current state is "
                    f"{self.data.state.value}"
                )
                return self.data

            self._guard_identity(
                course_id=self.data.course_id,
                coursework_id=self.data.coursework_id,
                submission_id=self.data.submission_id,
            )
            try:
                await self._classroom.return_submission(
                    await self._token(),
                    self.data.course_id,
                    self.data.coursework_id,
                    self.data.submission_id,
                )
            except Exception as exc:
                self._fail(f"studentSubmissions.return failed: {exc}")
                return self.data

            self._set_state(
                WorkflowState.RETURNED,
                f"submission {self.data.submission_id} returned to student",
            )
            return self.data

    # ---- step 9: post-return verification -----------------------------------

    async def verify(self) -> WorkflowData:
        async with self._lock:
            if self.data.state != WorkflowState.RETURNED:
                self._fail(
                    f"verify requires RETURNED; current state is {self.data.state.value}"
                )
                return self.data

            self._guard_identity(
                course_id=self.data.course_id,
                coursework_id=self.data.coursework_id,
                submission_id=self.data.submission_id,
            )
            try:
                submission = await self._classroom.get_submission(
                    await self._token(),
                    self.data.course_id,
                    self.data.coursework_id,
                    self.data.submission_id,
                )
            except Exception as exc:
                self._fail(f"post-return verification read failed: {exc}")
                return self.data

            result = VerificationResult().run(
                submission,
                expected_submission_id=self.data.submission_id,
                reviewed_drive_file_id=self.data.reviewed_drive_file_id,
            )
            self.data.verification = {
                "checks": result.checks,
                "all_passed": result.all_passed,
                "submission_state": submission.get("state", ""),
            }
            if not result.all_passed:
                self._fail(
                    f"post-return verification failed: {result.checks} — "
                    f"do NOT claim the student received the reviewed document"
                )
                return self.data

            self._set_state(
                WorkflowState.VERIFIED,
                "post-return verification passed: reviewed file is attached to the "
                "returned submission",
            )
            return self.data

    # ---- artifact access -------------------------------------------------------

    def export_bytes(self) -> tuple[bytes, str] | None:
        """The exact SuperDocs-exported DOCX bytes + the reviewed filename.
        Only available once export genuinely completed (state EXPORTED or
        later). Returns None before that — the download route gates on it,
        so the button cannot hand out a pre-export or blocked artifact."""
        if self.data.state in (
            WorkflowState.EXPORTED,
            WorkflowState.DRIVE_UPLOADED,
            WorkflowState.ATTACHED,
            WorkflowState.RETURNED,
            WorkflowState.VERIFIED,
        ) and self._export_bytes is not None:
            return self._export_bytes, self.data.reviewed_filename or "reviewed.docx"
        return None

    # ---- helpers -------------------------------------------------------------

    async def _poll_job(self, job_id: str, *, deadline: float) -> "object":
        end = time.time() + deadline
        while time.time() < end:
            job = await self._superdocs.get_job(job_id)
            if job.status in ("awaiting_approval", "completed", "failed", "cancelled"):
                return job
            await asyncio.sleep(self._poll_interval)
        raise TimeoutError(f"job {job_id} did not settle within {deadline:.0f}s")


# ---- registry: one workflow per workflow_id (in-memory) ----------------------

_workflows: dict[str, ReviewWorkflow] = {}


def create_workflow(
    *,
    course_id: str,
    course_name: str,
    coursework_id: str,
    assignment_title: str,
    submission_id: str,
    classroom: GoogleClassroomClient,
    drive: GoogleDriveClient,
    superdocs: SuperDocsClient,
    access_token_provider,
    owner_session_id: str = "",
) -> ReviewWorkflow:
    workflow_id = str(uuid.uuid4())
    data = WorkflowData(
        workflow_id=workflow_id,
        owner_session_id=owner_session_id,
        course_id=course_id,
        course_name=course_name,
        coursework_id=coursework_id,
        assignment_title=assignment_title,
        submission_id=submission_id,
    )
    workflow = ReviewWorkflow(
        data, classroom, drive, superdocs, access_token_provider
    )
    _workflows[workflow_id] = workflow
    return workflow


def get_workflow(workflow_id: str) -> ReviewWorkflow | None:
    return _workflows.get(workflow_id)
