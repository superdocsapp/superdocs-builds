from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.common import (
    ApprovalMode,
    JobStatus,
    ModelTier,
    PendingChange,
    ResponseMode,
    ThinkingDepth,
    Usage,
)


class EditByInstructionInput(BaseModel):
    session_id: str = Field(..., min_length=1)
    instruction: str = Field(..., min_length=1,
                              description="Natural-language edit instruction. Sent to SuperDocs as `message`.")
    document_html: str | None = Field(default=None, description=(
        "Only needed to LOAD or REPLACE a document, or sync out-of-band edits. "
        "Omit on follow-up turns — SuperDocs persists the document server-side "
        "once a session holds one."
    ))
    document_id: str | None = Field(default=None, description="Target a specific document in a multi-document session; omit to target the focused document.")
    model_tier: ModelTier = ModelTier.core
    thinking_depth: ThinkingDepth = ThinkingDepth.balanced
    approval_mode: ApprovalMode = ApprovalMode.approve_all
    response_mode: ResponseMode = ResponseMode.full
    run_async: bool = Field(default=False, description=(
        "False (default): synchronous /v1/chat, simplest for a quick single-"
        "section edit. True: /v1/chat/async + connector job worker — required "
        "if approval_mode='ask_every_time' (SuperDocs enforces this server-side; "
        "the connector validates it client-side too, see operations/edit_by_instruction.py)."
    ))


class EditByInstructionOutput(BaseModel):
    operation_id: str
    job_id: str | None = None
    session_id: str
    status: JobStatus
    changes_summary: str | None = None
    version_id: str | None = None
    updated_html: str | None = None
    pending_changes: list[PendingChange] = Field(default_factory=list, description="Populated when status is awaiting_approval with awaiting_kind=change_review.")
    usage: Usage | None = None
