"""Pydantic shapes for the SuperDocs REST contract this app depends on.

Replicated independently for classroom-app from the patterns established in
zoom-app (same endpoints, same field names — both apps talk to the same
third-party API). Response models allow extra fields and keep `status` a
plain string: SuperDocs is outside this repo's control, and a strict shape
would crash on an unknown field instead of surfacing it.

Contract facts confirmed against the live API by zoom-app and carried over:
- the upload wire field is `file_base64` (docs said `document_base64`)
- an empty pending_changes comes back as JSON null, not [] (coerced here)
- a completed job's changes live at result.document_changes.changes, with
  old_html/new_html (not html_before/html_after)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _none_to_empty_list(v: object) -> object:
    return [] if v is None else v


class _Response(BaseModel):
    model_config = ConfigDict(extra="allow")


class UploadResponse(_Response):
    session_id: str
    html: str | None = None
    chunks_count: int | None = None
    version_id: str | None = None


class ChatAsyncResponse(_Response):
    job_id: str
    session_id: str | None = None


class ChunkDiff(_Response):
    chunk_id: str | None = None
    operation: str | None = None
    old_html: str | None = None
    new_html: str | None = None


class DocumentChanges(_Response):
    updated_html: str | None = None
    changes: list[ChunkDiff] = Field(default_factory=list)

    _coerce_changes = field_validator("changes", mode="before")(_none_to_empty_list)


class PendingChange(_Response):
    """A proposed change awaiting human approval.

    Live-verified field names (2026-08, real API): the before/after text is
    `old_html`/`new_html`; `html_before`/`html_after` are always null on
    the wire and kept only for legacy tolerance. `change_id`,
    `document_id` and `ai_explanation` are also returned live."""

    chunk_id: str | None = None
    operation: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    change_id: str | None = None
    document_id: str | None = None
    ai_explanation: str | None = None
    # Legacy names — the live API never populates these (verified).
    html_before: str | None = None
    html_after: str | None = None


class JobMetadata(_Response):
    pending_changes: list[PendingChange] = Field(default_factory=list)
    awaiting_kind: str | None = None

    _coerce_pending_changes = field_validator("pending_changes", mode="before")(
        _none_to_empty_list
    )


class JobResult(_Response):
    response: str | None = None
    document_changes: DocumentChanges | None = None


class JobStatusResponse(_Response):
    job_id: str
    status: str  # deliberately not a Literal — see module docstring
    metadata: JobMetadata = Field(default_factory=JobMetadata)
    result: JobResult | None = None

    @property
    def document_changes(self) -> DocumentChanges | None:
        return self.result.document_changes if self.result else None


class ExportResult(BaseModel):
    """Export returns a binary file, not JSON — bundles the bytes, their
    content-type, and any non-fatal warnings from the X-Export-Warnings
    header."""

    content: bytes
    content_type: str
    warnings: list[str] = Field(default_factory=list)
