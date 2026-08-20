"""Domain models for the Classroom feedback workflow.

The identity invariants live here by construction: every model that
identifies a submission carries the exact course_id / coursework_id /
submission_id triplet, and the orchestrator only ever passes those stored
values through. There is no "find the matching submission" anywhere —
identity comes from IDs the teacher selected, never from filenames.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowState(StrEnum):
    DOCUMENT_RETRIEVED = "document_retrieved"
    SUPERDOCS_UPLOADED = "superdocs_uploaded"
    REVIEW_GENERATED = "review_generated"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVAL_COMPLETE = "approval_complete"
    BLOCKED = "blocked"
    EXPORTED = "exported"
    DRIVE_UPLOADED = "drive_uploaded"
    ATTACHED = "attached"
    RETURNED = "returned"
    VERIFIED = "verified"
    ERROR = "error"


class ReviewDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PendingChange(BaseModel):
    chunk_id: str
    # The identifier the SuperDocs approve endpoint requires per change —
    # distinct from chunk_id (live-verified: they always differ). The
    # approval payload must use change_id.
    change_id: str = ""
    operation: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None
    # True when the proposed replacement is textually identical to the
    # original (normalized). No-op changes stay in the record for
    # auditability but require no decision and are never sent to the
    # approval endpoint.
    is_noop: bool = False
    decision: ReviewDecision = ReviewDecision.PENDING


class TimelineEntry(BaseModel):
    state: WorkflowState
    detail: str
    at: float


class WorkflowData(BaseModel):
    """The full identity + progress record of one review workflow.

    Every ID here was captured from the API response that produced it and
    is passed verbatim to every later call — never recomputed, never
    guessed from a filename."""

    workflow_id: str
    # The signed session that created this workflow. Artifact-download and
    # other sensitive operations check ownership against it, so one
    # workflow's reviewed document cannot be fetched by another session.
    owner_session_id: str = ""

    # ---- Classroom identity (from the teacher's selections) ----
    course_id: str
    course_name: str = ""
    coursework_id: str
    assignment_title: str = ""
    submission_id: str
    student_user_id: str = ""
    student_display: str = ""

    # ---- The student's original attachment ----
    original_drive_file_id: str = ""
    original_filename: str = ""
    original_mime_type: str = ""

    # ---- SuperDocs ----
    superdocs_session_id: str = ""
    review_job_id: str = ""
    # Semantic review configuration selected by the teacher. SuperDocs model
    # names are derived server-side and never accepted from the browser.
    review_mode: str = "proofreading"
    review_depth: str = "standard"
    pending_changes: list[PendingChange] = Field(default_factory=list)
    # chunk_id -> "approved" | "rejected"
    review_decisions: dict[str, str] = Field(default_factory=dict)
    approval_mode_used: str = ""  # "ask_every_time" — native HITL, or ""

    # ---- Reviewed artifact ----
    reviewed_drive_file_id: str = ""
    reviewed_filename: str = ""

    # ---- Progress ----
    state: WorkflowState = WorkflowState.DOCUMENT_RETRIEVED
    error: str = ""
    blocker_reason: str = ""
    timeline: list[TimelineEntry] = Field(default_factory=list)

    # ---- Verification ----
    verification: dict[str, Any] = Field(default_factory=dict)

    def actionable_changes(self) -> list[PendingChange]:
        return [c for c in self.pending_changes if not c.is_noop]

    def decision_counts(self) -> dict[str, int]:
        counts = {"approved": 0, "rejected": 0, "pending": 0, "noop": 0}
        for change in self.pending_changes:
            if change.is_noop:
                counts["noop"] += 1
            else:
                counts[change.decision.value] += 1
        return counts

    def all_decided(self) -> bool:
        actionable = self.actionable_changes()
        return bool(actionable) and all(
            c.decision != ReviewDecision.PENDING for c in actionable
        )


class VerificationResult(BaseModel):
    checks: dict[str, bool] = Field(default_factory=dict)
    all_passed: bool = False

    def run(
        self, submission: dict, expected_submission_id: str, reviewed_drive_file_id: str
    ) -> "VerificationResult":
        from app.google.classroom import submission_attachments

        actual_id = submission.get("id", "")
        attached = [
            a.get("driveFile", {}).get("id", "")
            for a in submission_attachments(submission)
            if a.get("driveFile")
        ]
        self.checks = {
            "submission_exists": bool(submission),
            "submission_id_unchanged": actual_id == expected_submission_id,
            "reviewed_file_attached": reviewed_drive_file_id in attached,
        }
        self.all_passed = all(self.checks.values())
        return self
