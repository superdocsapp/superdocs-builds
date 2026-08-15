"""
Shared enums and value types used across every operation's input/output schema.
Mirrors the vocabulary SuperDocs itself uses (docs.superdocs.app) so a recipe
author's input maps 1:1 onto documented API fields — no connector-invented
naming to relearn.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ModelTier(StrEnum):
    core = "core"
    turbo = "turbo"
    pro = "pro"
    max = "max"


class ThinkingDepth(StrEnum):
    fast = "fast"
    balanced = "balanced"
    deep = "deep"


class ApprovalMode(StrEnum):
    approve_all = "approve_all"
    ask_every_time = "ask_every_time"


class ResponseMode(StrEnum):
    full = "full"
    compact = "compact"


class JobStatus(StrEnum):
    """Exactly the statuses documented at docs.superdocs.app/guides/async-jobs."""
    pending = "pending"
    in_progress = "in_progress"
    awaiting_approval = "awaiting_approval"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class AwaitingKind(StrEnum):
    """Distinguishes the two reasons a job can sit in `awaiting_approval` — see
    docs.superdocs.app/guides/human-in-the-loop's 'two flavours' warning.
    Calling the wrong resume endpoint for the wrong kind returns 409."""
    change_review = "change_review"  # -> resolve via submit_for_approval
    continue_prompt = "continue_prompt"  # -> resolve via /chat/{session}/continue (not modeled as a first-class op here; see README)


class ChangeOperation(StrEnum):
    edit = "edit"
    create = "create"
    delete = "delete"


class ExportFormat(StrEnum):
    docx = "docx"
    pdf = "pdf"
    html = "html"
    markdown = "markdown"
    txt = "txt"
    doc = "doc"  # legacy alias, accepted not recommended — see docs


SUPPORTED_UPLOAD_EXTENSIONS = frozenset({
    "pdf", "docx", "txt", "rtf", "md", "html", "htm",
})
# Per docs.superdocs.app: "Legacy .doc is unsupported and should be converted
# to .docx." Kept as an explicit constant (rather than just an absence from
# the set above) so error messages and tests can name it precisely.
LEGACY_UNSUPPORTED_EXTENSIONS = frozenset({"doc"})


class PendingChange(BaseModel):
    """One entry from `metadata.pending_changes` (poll) or a `proposed_change_batch`
    SSE event's `changes[]` (stream) — same shape either way per the docs."""
    change_id: str
    operation: ChangeOperation
    chunk_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None
    insert_after_chunk_id: str | None = None
    document_id: str | None = None


class Usage(BaseModel):
    monthly_used: int | None = None
    monthly_limit: int | None = None
    monthly_remaining: int | None = None
    was_billable: bool | None = None
    ops_charged: int | None = None
    quota_exhausted: bool | None = None
    subscription_tier: str | None = None


class ExportOptions(BaseModel):
    """Mirrors POST /v1/documents/export's `options` object exactly."""
    paper_size: Literal["Letter", "A4", "A3", "Legal"] | None = None
    orientation: Literal["portrait", "landscape"] | None = None
    margins: Literal["narrow", "normal", "wide", "custom"] | None = None
    custom_margins_inches: dict[str, float] | None = None
    filename: str | None = None
    embed_images: bool | None = None
    watermark_text: str | None = Field(default=None, max_length=64)
    watermark_opacity: float | None = Field(default=None, ge=0.05, le=1.0)
