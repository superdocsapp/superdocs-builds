from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.common import AwaitingKind, JobStatus, PendingChange, Usage


class PollInput(BaseModel):
    job_id: str = Field(..., min_length=1)


class JobResult(BaseModel):
    """Populated only when status == completed."""
    response: str | None = None
    updated_html: str | None = None
    version_id: str | None = None
    changes_summary: str | None = None
    usage: Usage | None = None


class ContinuePrompt(BaseModel):
    """Populated only when awaiting_kind == continue_prompt (a large edit
    paused mid-way, distinct from a HITL change review)."""
    message: str
    done: int
    total: int
    remaining: int


class PollOutput(BaseModel):
    job_id: str
    status: JobStatus
    awaiting_kind: AwaitingKind | None = Field(default=None, description="Set only when status == awaiting_approval.")
    result: JobResult | None = None
    error: str | None = Field(default=None, description="Set only when status == failed.")
    pending_changes: list[PendingChange] = Field(default_factory=list)
    continue_prompt: ContinuePrompt | None = None
