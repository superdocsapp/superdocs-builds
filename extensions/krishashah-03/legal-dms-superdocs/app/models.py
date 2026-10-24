"""
Pydantic models for the HTTP layer. Internal domain objects (Matter, Document,
Version, User) live in app/dms/store.py and are intentionally plain dataclasses -
these models are only the wire format.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentSummary(BaseModel):
    document_id: str
    matter_id: str
    title: str
    current_version: int
    checked_out_by: str | None = None


class UploadDocumentResponse(BaseModel):
    document_id: str
    matter_id: str
    title: str
    version_number: int
    byte_size: int


class CheckoutResponse(BaseModel):
    document_id: str
    matter_id: str
    session_id: str
    checked_out_by: str
    version_loaded: int
    superdocs_chunks: int


class EditRequest(BaseModel):
    instruction: str = Field(..., min_length=1, description="Natural-language edit instruction")
    model_tier: Literal["core", "turbo", "pro", "max"] | None = None
    model_config = {"protected_namespaces": ()}


class ProposedChange(BaseModel):
    """
    One AI-proposed edit awaiting review. Field names match SuperDocs's real
    response, confirmed live: a "create" (new paragraph) had old_html=null
    and chunk_id="new" (not a stable location for that operation type).
    """

    change_id: str
    operation: str | None = None  # "create" | "update" | "delete" (per SuperDocs docs)
    chunk_id: str | None = None
    document_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None


class EditResponse(BaseModel):
    document_id: str
    session_id: str
    job_id: str
    status: str
    pending_changes: list[ProposedChange] = Field(default_factory=list)


class ChangeDecision(BaseModel):
    change_id: str
    approved: bool
    feedback: str | None = None


class ReviewRequest(BaseModel):
    job_id: str
    decisions: list[ChangeDecision]


class ReviewResponse(BaseModel):
    document_id: str
    session_id: str
    job_id: str
    status: str
    remaining_pending_changes: list[ProposedChange] = Field(default_factory=list)


class CheckinRequest(BaseModel):
    version_comment: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CheckinResponse(BaseModel):
    document_id: str
    matter_id: str
    new_version: int
    version_comment: str
    checked_in_by: str
    byte_size: int


class VersionSummary(BaseModel):
    version_number: int
    comment: str
    created_by: str
    created_at: str
    byte_size: int
    has_exported_file: bool


class PrecedentHit(BaseModel):
    document_id: str
    matter_id: str
    title: str
    version: int
    score: float
    snippet: str


class PrecedentSearchResponse(BaseModel):
    query: str
    hits: list[PrecedentHit]
    ai_summary: str | None = None