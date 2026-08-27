"""Typed models mirroring the SuperDocs REST surface we depend on.

Field names match the documented API verbatim so the live client is a thin, honest mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Usage(BaseModel):
    """The `usage` block SuperDocs returns; how we know what a run actually cost."""

    model_config = {"extra": "ignore"}

    monthly_used: int = 0
    monthly_limit: int = 0
    ops_charged: int = 0
    was_billable: bool = False
    quota_exhausted: bool = False


class ChunkDiff(BaseModel):
    """One proposed edit to one chunk — the shape inside `chunk_diffs` / `pending_changes`."""

    model_config = {"extra": "ignore"}

    chunk_id: str
    change_id: str = ""  # the id `approve` keys on (distinct from chunk_id; chunk_id 500s)
    operation: str
    old_html: str = ""
    new_html: str = ""
    chunk_type: str = ""
    ai_explanation: str = ""  # SuperDocs' natural-language note when its AI authored the edit


class UploadResult(BaseModel):
    model_config = {"extra": "ignore"}

    html: str
    session_id: str
    chunks_count: int
    version_id: str


class Job(BaseModel):
    """An async job. `chunk_diffs` is the already-parsed form of `metadata.pending_changes`."""

    model_config = {"extra": "ignore"}

    job_id: str
    status: JobStatus
    chunk_diffs: list[ChunkDiff] = Field(default_factory=list)
    document_html: str | None = None
    usage: Usage | None = None
    error: str | None = None


class ApprovalDecision(BaseModel):
    """One item in the item-by-item human gate. ``approve`` keys on ``change_id``, not chunk_id."""

    change_id: str
    approved: bool
    feedback: str = ""


class ApproveResult(BaseModel):
    model_config = {"extra": "ignore"}

    status: str
    applied_count: int
    denied_count: int
    job_id: str | None = None


@dataclass
class ExportResult:
    """A finished file. Bytes, not a model, because it is binary content."""

    content: bytes
    content_type: str
    filename: str
    warnings: list[dict[str, Any]] = field(default_factory=list)
