"""
Approval schemas.

CRITICAL, per docs.superdocs.app/guides/human-in-the-loop: the top-level
`approved` field is REQUIRED on every call to POST /v1/chat/{session_id}/approve
— including batch/per-change shapes. Omitting it is documented as "the single
most common integration trap" and returns a generic 422. ApprovalInput makes
this structurally hard to get wrong: `approved` has no default, so a caller
must supply it, and the operation layer (operations/submit_for_approval.py)
always sends it at the top level of the outgoing request regardless of which
shape (single / batch-same / batch-per-change) is being used.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ChangeDecision(BaseModel):
    """One entry in a batch decision. `approved` here is optional — if omitted,
    the top-level ApprovalInput.approved is used as the default for this entry,
    exactly matching SuperDocs' documented fallback behavior."""
    change_id: str
    approved: bool | None = None
    feedback: str | None = None


class ApprovalInput(BaseModel):
    session_id: str = Field(..., min_length=1)
    job_id: str = Field(..., min_length=1)
    approved: bool = Field(..., description=(
        "REQUIRED at the top level always — this is the default decision for "
        "any entry in `changes` that doesn't specify its own `approved`, and is "
        "the sole decision when `change_ids`/`changes` is omitted (single-change shape)."
    ))
    change_ids: list[str] | None = Field(default=None, description=(
        "Batch-same shape: approve/deny this list of change_ids with the single "
        "top-level `approved` decision. Mutually exclusive with `changes`."
    ))
    changes: list[ChangeDecision] | None = Field(default=None, description=(
        "Batch-per-change shape: independent approved/feedback per change_id. "
        "Mutually exclusive with `change_ids`."
    ))
    change_id: str | None = Field(default=None, description="Single-change shape: the one change_id being decided.")
    feedback: str | None = Field(default=None, description="Feedback for a single denied change (single-change shape only).")

    @model_validator(mode="after")
    def at_most_one_shape(self) -> ApprovalInput:
        shapes_used = sum([
            self.change_id is not None,
            self.change_ids is not None,
            self.changes is not None,
        ])
        if shapes_used > 1:
            raise ValueError(
                "ApprovalInput accepts exactly one shape: change_id (single), "
                "change_ids (batch-same), or changes (batch-per-change) — not more than one."
            )
        return self


class ApprovalOutput(BaseModel):
    job_id: str
    status: str = Field(..., description="The job's status immediately after the decision was recorded (SuperDocs resumes processing asynchronously; poll_for_completion to observe the outcome).")
    applied: list[str] = Field(default_factory=list, description="change_ids that were approved and applied.")
    rejected: list[str] = Field(default_factory=list, description="change_ids that were denied and discarded.")
