from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ApprovalMode = Literal["approve_all", "ask_every_time"]
ExportFormat = Literal["docx", "pdf", "html", "markdown", "txt"]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProposedChange(ApiModel):
    change_id: str
    operation: str
    chunk_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None
    batch_id: str | None = None
    batch_total: int | None = None
    insert_after_chunk_id: str | None = None
    document_id: str | None = None


class ProposedChangeBatch(ApiModel):
    type: str
    batch_id: str
    batch_total: int
    changes: list[ProposedChange]


class DocumentChanges(ApiModel):
    updated_html: str | None = None
    version_id: str | None = None
    chunk_diffs: list[dict[str, Any]] = Field(default_factory=list)


class ChatResult(ApiModel):
    response: str | None = None
    document_changes: DocumentChanges | None = None
    usage: dict[str, Any] | None = None


class Job(ApiModel):
    job_id: str
    session_id: str | None = None
    status: str
    result: ChatResult | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {"completed", "failed", "cancelled"}

    @property
    def needs_input(self) -> bool:
        return self.status == "awaiting_approval"


class ApprovalDecision(BaseModel):
    change_id: str
    approved: bool
    feedback: str | None = None


class UploadResult(ApiModel):
    filename: str
    chunks_count: int | None = None
    html: str | None = None
    upload_id: str | None = None
    version_id: str | None = None
    page_setup: dict[str, Any] | None = None


class DocumentExport(BaseModel):
    content: bytes
    content_type: str | None = None
    warnings: str | None = None


class ProgressEvent(BaseModel):
    type: str
    content: Any | None = None
    sequence: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Session(ApiModel):
    id: str | None = None
    session_id: str | None = None
    title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SessionHistory(ApiModel):
    session_id: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    document_html: str | None = None


class SavedDocument(ApiModel):
    id: str | None = None
    document_id: str | None = None
    filename: str | None = None
    status: str | None = None
    archived: bool | None = None


class DocumentDetail(SavedDocument):
    html: str | None = None
    session_id: str | None = None
    version_id: str | None = None


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None
