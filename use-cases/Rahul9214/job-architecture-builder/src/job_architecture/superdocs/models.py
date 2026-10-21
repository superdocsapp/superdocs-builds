"""Typed SuperDocs adapter models. No HTTP types leak through here."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from job_architecture.superdocs.errors import ExportError


@dataclass(frozen=True)
class SuperDocsSettings:
    api_key: str
    base_url: str = "https://api.superdocs.app"
    timeout_seconds: float = 120.0
    poll_interval_seconds: float = 2.0
    poll_max_wait_seconds: float = 300.0

    def __repr__(self) -> str:
        return (
            "SuperDocsSettings("
            f"base_url={self.base_url!r}, timeout_seconds={self.timeout_seconds}, "
            "api_key='[redacted]')"
        )

    def __str__(self) -> str:
        return repr(self)


@dataclass(frozen=True)
class DocumentRef:
    """Stable ids for a document in a session. Never a mutable 'current document'."""

    document_id: str
    durable_document_id: str | None = None
    title: str | None = None
    focused: bool = False
    chunks_count: int | None = None
    version_id: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class SessionRoster:
    session_id: str
    documents: tuple[DocumentRef, ...]
    focused_document_id: str | None

    def document(self, document_id: str) -> DocumentRef:
        for item in self.documents:
            if item.document_id == document_id or item.durable_document_id == document_id:
                return item
        raise KeyError(document_id)


@dataclass(frozen=True)
class UploadResult:
    session_id: str
    document: DocumentRef
    roster: SessionRoster
    filename: str | None = None
    html: str | None = None
    operation_key: str | None = None


@dataclass(frozen=True)
class TemplateRef:
    template_id: str
    name: str | None = None
    filename: str | None = None


@dataclass(frozen=True)
class SavedDocument:
    document_id: str
    title: str | None = None
    session_count: int | None = None
    updated_at: str | None = None
    preview_html: str | None = None


@dataclass(frozen=True)
class ProposedChange:
    change_id: str
    operation: str
    chunk_id: str | None = None
    document_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    reason: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def before(self) -> str | None:
        return self.old_html

    @property
    def after(self) -> str | None:
        return self.new_html


@dataclass(frozen=True)
class ReviewDecision:
    change_id: str
    approved: bool
    feedback: str | None = None


@dataclass(frozen=True)
class ApprovalResult:
    job_id: str
    session_id: str
    decided: tuple[ReviewDecision, ...]
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def all_approved(self) -> bool:
        return bool(self.decided) and all(item.approved for item in self.decided)


@dataclass(frozen=True)
class AsyncJobHandle:
    job_id: str
    session_id: str
    status: str
    normalized_status: str
    message: str | None = None
    operation_key: str | None = None


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    session_id: str
    raw_status: str
    status: str
    progress: int
    error: str | None
    pending_changes: tuple[ProposedChange, ...]
    awaiting_kind: str | None
    result: Mapping[str, Any] | None
    metadata: Mapping[str, Any]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class ExportResult:
    filename: str
    content_type: str | None
    byte_count: int
    destination: str | None = None
    operation_key: str | None = None


DOCUMENTED_EXPORT_BODY_KEYS = frozenset(
    {"html", "session_id", "upload_id", "format", "options", "filename"}
)
DOCUMENTED_EXPORT_FORMATS = frozenset({"docx", "pdf", "html", "markdown", "txt", "doc"})


@dataclass(frozen=True)
class ExportRequest:
    """POST /v1/documents/export body from current SuperDocs docs (llms-full.txt).

    Documented fields: html, session_id, upload_id, format, options, filename.
    The API requires one of html / session_id / upload_id. Session-only export
    returns the session's current/default document. This integration always
    sends non-empty html so the artifact is deterministic. document_id and
    durable_document_id are not documented on this endpoint.
    """

    session_id: str
    html: str
    format: str = "docx"
    filename: str | None = None

    def __post_init__(self) -> None:
        session_id = self.session_id.strip() if isinstance(self.session_id, str) else ""
        html = self.html.strip() if isinstance(self.html, str) else ""
        fmt = (self.format or "docx").strip()
        filename = self.filename.strip() if isinstance(self.filename, str) and self.filename.strip() else None
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "html", html)
        object.__setattr__(self, "format", fmt)
        object.__setattr__(self, "filename", filename)
        if not html:
            raise ExportError("Export HTML is empty; refusing SuperDocs call")
        if not session_id:
            raise ExportError("Export requires session_id")
        if fmt not in DOCUMENTED_EXPORT_FORMATS:
            raise ExportError(f"Unsupported export format {fmt!r}")

    def json_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "html": self.html,
            "session_id": self.session_id,
            "format": self.format,
        }
        if self.filename:
            body["filename"] = self.filename
            body["options"] = {"filename": self.filename}
        extra = set(body) - DOCUMENTED_EXPORT_BODY_KEYS
        if extra:
            raise ExportError(f"Refusing undocumented export fields: {sorted(extra)}")
        return body


@dataclass(frozen=True)
class SearchAccepted:
    """Search is an async SuperDocs chat turn with cross-session search enabled."""

    handle: AsyncJobHandle
    query: str
