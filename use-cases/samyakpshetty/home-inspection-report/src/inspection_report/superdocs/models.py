"""Typed models for the SuperDocs surface this build depends on.

Field names match the live API verbatim, so the client stays a thin, honest mapping. Where a
name differs from the published documentation, the difference is recorded in a comment and
was established by calling the real endpoint — the documentation and the API disagree in
several places and the API is what ships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImageUpload(BaseModel):
    """The result of uploading one photograph.

    Two URLs come back, and the difference matters. ``url`` is stable and permanent;
    ``view_url`` is the same object with a 24-hour signature on it. I verified that ``url``
    is readable with **no credentials at all**, so it is a capability, not an identifier:
    treat it as a secret, never log it, never commit it. Only ``url`` is persisted, because
    ``view_url`` would be stale within a day.
    """

    model_config = {"extra": "ignore"}

    url: str
    content_type: str = ""
    size: int = 0

    def __repr__(self) -> str:  # pragma: no cover - defensive, mirrors __str__
        return self.__str__()

    def __str__(self) -> str:
        """Never render the URL. A stray f-string must not leak a photograph."""
        return f"ImageUpload(size={self.size}, content_type={self.content_type!r}, url=<redacted>)"


class TemplateRef(BaseModel):
    """A registered report format, as SuperDocs lists it."""

    model_config = {"extra": "ignore"}

    id: str
    name: str
    file_extension: str = ""
    file_size: int = 0
    created_at: str = ""


class ExportOptions(BaseModel):
    """Export customisation. Mirrors the API's ``options`` object exactly."""

    paper_size: str = "Letter"
    orientation: str = "portrait"
    margins: str = "normal"
    filename: str | None = None
    # HTML export only. True embeds image bytes rather than referencing them by URL, which
    # is why this build sets it: an exported HTML file must not carry capability URLs.
    embed_images: bool = False
    watermark_text: str | None = None


class ChunkDiff(BaseModel):
    """One proposed edit to one chunk.

    ``change_id`` is what ``approve`` keys on. Approving by ``chunk_id`` returns a 500 — this
    was established against the live API and contradicts the published documentation.

    Not every edit is a replacement. ``operation`` is ``'edit' | 'create' | 'delete'``, and
    the side that does not exist arrives as ``null`` — a deletion has no ``new_html``, an
    insertion has no ``old_html``. **The API documents this correctly**
    (``anyOf: [string, null]`` on both, and on ``chunk_id``); I typed them as plain ``str``
    and the first request that asked for a section to be *removed* made the whole job
    unparseable, after it had already been charged for. My bug, from not reading the schema.
    Null is normalised to the empty string here, in one place, so nothing downstream has to
    care, and ``operation`` still says which kind of edit it is.
    """

    model_config = {"extra": "ignore"}

    chunk_id: str = ""
    change_id: str = ""
    operation: str = ""
    old_html: str = ""
    new_html: str = ""
    chunk_type: str = ""
    ai_explanation: str = ""

    @field_validator(
        "chunk_id",
        "change_id",
        "operation",
        "old_html",
        "new_html",
        "chunk_type",
        "ai_explanation",
        mode="before",
    )
    @classmethod
    def _null_is_absent(cls, value: Any) -> Any:
        return "" if value is None else value

    @property
    def is_deletion(self) -> bool:
        """The change removes content rather than replacing it."""
        return bool(self.old_html) and not self.new_html


class Usage(BaseModel):
    """What a request actually cost, and what is left.

    What a job cost rides back on the job itself. The *balance* is a separate question and
    has a free answer: ``GET /v1/users/me/promotions`` accepts an API key and reports the
    promo bucket's ``ops_remaining``. (``/v1/users/me/usage`` and ``/limits`` reject API keys
    outright, which is what sent me looking in the wrong place first.)
    """

    model_config = {"extra": "ignore"}

    @model_validator(mode="before")
    @classmethod
    def _nulls_are_absent(cls, data: Any) -> Any:
        """Treat an explicit ``null`` as "not sent", so the field default stands.

        The service sends `null` for fields it has no value for — seen live on 27 Aug 2026,
        `bucket_used: null` on a job that had just succeeded, which failed the whole parse and
        surfaced in the interface as a pydantic ValidationError where a report should have
        been. Defaulting a missing key while rejecting a null one is a distinction the sender
        does not make, so we should not either. Dropped here rather than widening each field
        to `| None`, which would push the null into arithmetic downstream.
        """
        if isinstance(data, dict):
            return {key: value for key, value in data.items() if value is not None}
        return data

    ops_charged: int = 0
    was_billable: bool = False
    quota_exhausted: bool = False
    bucket_used: str = ""
    monthly_used: int = 0
    monthly_limit: int = 0
    monthly_remaining: int = 0
    promotions: list[dict[str, Any]] = Field(default_factory=list)

    def ops_remaining(self) -> int:
        """Remaining operations, preferring the promotional bucket when one is active."""
        for promo in self.promotions:
            remaining = promo.get("ops_remaining")
            if isinstance(remaining, int):
                return remaining
        return self.monthly_remaining


class Job(BaseModel):
    """An async chat job.

    ``document_html`` is where a completed job's document actually lives once assembled from
    the response: the top-level ``document_html`` field is ``None`` on a completed job and
    the content sits at ``result.document_changes.updated_html``.
    """

    model_config = {"extra": "ignore"}

    job_id: str
    status: JobStatus
    chunk_diffs: list[ChunkDiff] = Field(default_factory=list)
    document_html: str | None = None
    requires_approval: bool = False
    usage: Usage | None = None
    error: str | None = None


class UploadResult(BaseModel):
    model_config = {"extra": "ignore"}

    html: str = ""
    session_id: str = ""
    chunks_count: int = 0
    version_id: str = ""


class ApprovalDecision(BaseModel):
    """One item in the item-by-item human gate."""

    change_id: str
    approved: bool
    feedback: str = ""


class ApproveResult(BaseModel):
    """What `approve` answers with.

    ``applied_count`` and ``denied_count`` are **not returned by the live service** — its
    response is `{"status", "message", "batch_complete"}` and nothing else — so on the live
    path they are always the default 0, however many changes actually landed. The fake fills
    them because it can. Do not read them as a count of work done; the only honest check is to
    read the document back, which is what the export path does. Recorded here because the
    zero was briefly mistaken for a service defect, and it is our own default.
    """

    model_config = {"extra": "ignore"}

    status: str = ""
    applied_count: int = 0
    denied_count: int = 0
    job_id: str | None = None


@dataclass
class ExportResult:
    """A finished file. Bytes, not a model, because it is binary content."""

    content: bytes
    content_type: str
    filename: str
    warnings: list[dict[str, Any]] = field(default_factory=list)
