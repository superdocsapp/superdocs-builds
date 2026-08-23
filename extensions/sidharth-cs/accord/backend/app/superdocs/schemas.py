"""Pydantic shapes for the SuperDocs REST contract this app depends on.

Only the fields client.py actually reads or sends. The endpoint map this
was built against — including the places the live API disagrees with the
published docs — is recorded in PROGRESS.md and SUPERDOCS_BUGS.md. Response models allow extra
fields and leave `status` as a plain string rather than a closed enum:
SuperDocs is a third-party API outside this repo's control, and a strict
shape would crash this client on a field or status value it doesn't
recognize instead of surfacing it — see "SuperDocs API contract changes" in
the plan's Technical Trade-offs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _none_to_empty_list(v: object) -> object:
    # Confirmed against the live API: an empty "pending changes" list comes
    # back as JSON null, not `[]` or an absent key. A plain `list[...]`
    # field rejects null outright — this is the coercion that keeps
    # "nothing pending" from being a crash instead of an empty list.
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
    # Field names confirmed against a live completed job's raw JSON under
    # approval_mode=auto (see PROGRESS.md M3) — `old_html`/`new_html`, not
    # the `html_before`/`html_after` this was originally built from. The
    # wire array itself is `document_changes.changes`; `document_changes.
    # chunk_diffs` was observed present-but-null on every live job tested,
    # so this model now serves `changes`. `operation: "create"` is
    # confirmed live for an addition; `"delete"`/`"update"` are inferred
    # from that CRUD-style naming, not independently confirmed — see
    # integrity.py's own note where this matters.
    chunk_id: str | None = None
    operation: str | None = None
    old_html: str | None = None
    new_html: str | None = None


class DocumentChanges(_Response):
    updated_html: str | None = None
    changes: list[ChunkDiff] = Field(default_factory=list)

    _coerce_changes = field_validator("changes", mode="before")(_none_to_empty_list)


class PendingChange(_Response):
    """One AI-proposed document change awaiting approval (HITL gate).

    Field names confirmed against the live API (see capability experiments
    E2/E5): `change_id`, `operation`, `chunk_id`, `old_html`/`new_html`,
    `ai_explanation`. `chunk_id` is `"new"` for create operations — there is
    no anchor chunk until the change commits."""
    change_id: str | None = None
    operation: str | None = None
    chunk_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None


class JobMetadata(_Response):
    pending_changes: list[PendingChange] = Field(default_factory=list)
    awaiting_kind: str | None = None

    _coerce_pending_changes = field_validator("pending_changes", mode="before")(_none_to_empty_list)


class JobResult(_Response):
    # The real location of a completed job's edit output — confirmed live;
    # the top-level `document_changes` this was originally built from
    # doesn't exist on the wire at all. See JobStatusResponse.document_changes.
    response: str | None = None
    document_changes: DocumentChanges | None = None


class JobStatusResponse(_Response):
    job_id: str
    # Not a Literal — deliberately, see module docstring.
    status: str
    metadata: JobMetadata = Field(default_factory=JobMetadata)
    result: JobResult | None = None

    @property
    def document_changes(self) -> DocumentChanges | None:
        """Kept as the read path every caller already uses (session.py,
        tests) — only the source moved, from an assumed top-level field to
        the confirmed real `result.document_changes`."""
        return self.result.document_changes if self.result else None


class ExportResult(BaseModel):
    """Export returns a binary file, not JSON — this just bundles what
    client.export() hands back: the bytes, their content-type, and any
    non-fatal warnings SuperDocs reported in the X-Export-Warnings header."""

    content: bytes
    content_type: str
    warnings: list[str] = Field(default_factory=list)
