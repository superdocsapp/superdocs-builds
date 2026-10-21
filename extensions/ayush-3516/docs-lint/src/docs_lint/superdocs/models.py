"""Typed views over the SuperDocs API payloads this project touches.

Field names marked UNVERIFIED come from prose in the documentation rather than a published response
schema - the OpenAPI spec publishes `{}` for several 200 responses (logged as a bug in
PROGRESS.md). Everything here tolerates missing keys and keeps the raw payload, so an unexpected
shape degrades into "we did not learn anything from this response" rather than a crash.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _first(payload: dict[str, Any], *names: str, default: Any = None) -> Any:
    """Return the first present, non-None key from `names`.

    The documented field names are not fully pinned down, so the client accepts the plausible
    spellings rather than betting the run on one guess.
    """
    for name in names:
        value = payload.get(name)
        if value is not None:
            return value
    return default


def decode_maybe_json_string(value: Any) -> Any:
    """Parse a value that may have been JSON-encoded a second time.

    Proposed-change content arrives as a JSON-encoded string and needs a second parse, while the
    final result is already an object. This is the single most common reason integrators see diff
    cards where every field reads `undefined`, so it is handled once, here, rather than at each
    call site.

    A string that is not JSON is returned unchanged - prose content is the normal case and must
    survive untouched.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in '"[{':
        return value
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        return value


def as_html_text(value: Any) -> str | None:
    """Coerce a possibly double-encoded change payload down to an HTML string."""
    decoded = decode_maybe_json_string(value)
    if decoded is None:
        return None
    if isinstance(decoded, str):
        return decoded
    if isinstance(decoded, dict):
        for key in ("html", "content", "text", "value"):
            inner = decoded.get(key)
            if isinstance(inner, str):
                return inner
    return json.dumps(decoded)


class JobStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

    @property
    def needs_caller(self) -> bool:
        """The job has stopped and will not move again until we act."""
        return self is JobStatus.AWAITING_APPROVAL

    @classmethod
    def parse(cls, raw: Any) -> JobStatus:
        """Unknown statuses map to IN_PROGRESS rather than raising.

        A status we do not recognise is not grounds to abandon a job that may be progressing
        normally; the poll loop's own deadline is the backstop.
        """
        if isinstance(raw, cls):
            return raw
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return cls.IN_PROGRESS


class ChangeOperation(StrEnum):
    EDIT = "edit"
    CREATE = "create"
    DELETE = "delete"

    @classmethod
    def parse(cls, raw: Any) -> ChangeOperation:
        try:
            return cls(str(raw).strip().lower())
        except ValueError:
            return cls.EDIT


class PendingChange(BaseModel):
    """One AI-proposed modification awaiting a human decision.

    Which of `old_html` / `new_html` is populated depends on `operation`: an edit carries both, a
    create carries only `new_html` plus `insert_after_chunk_id`, a delete carries only `old_html`.
    """

    model_config = ConfigDict(frozen=True)

    change_id: str
    operation: ChangeOperation = ChangeOperation.EDIT
    chunk_id: str | None = None
    old_html: str | None = None
    new_html: str | None = None
    ai_explanation: str | None = None
    insert_after_chunk_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> PendingChange:
        return cls(
            change_id=str(_first(payload, "change_id", "id", default="")),
            operation=ChangeOperation.parse(_first(payload, "operation", "op", default="edit")),
            chunk_id=_first(payload, "chunk_id", "chunkId"),
            old_html=as_html_text(_first(payload, "old_html", "oldHtml", "before")),
            new_html=as_html_text(_first(payload, "new_html", "newHtml", "after")),
            ai_explanation=_first(payload, "ai_explanation", "explanation", "reason"),
            insert_after_chunk_id=_first(payload, "insert_after_chunk_id", "insertAfterChunkId"),
            raw=payload,
        )

    @property
    def target_chunk_id(self) -> str | None:
        """The chunk this change is anchored to, whether it edits it or inserts after it."""
        return self.chunk_id or self.insert_after_chunk_id


class Job(BaseModel):
    """An async chat job. `pending_changes` is only populated at `awaiting_approval`."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    status: JobStatus
    pending_changes: tuple[PendingChange, ...] = ()
    awaiting_kind: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    usage: JobUsage | None = None
    session_id: str | None = None
    progress: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Job:
        metadata = _first(payload, "metadata", "meta", default={}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        raw_changes = _first(metadata, "pending_changes", "pendingChanges", default=[]) or []
        if not isinstance(raw_changes, list):
            raw_changes = []
        result = _first(payload, "result")
        result = result if isinstance(result, dict) else None
        return cls(
            job_id=str(_first(payload, "job_id", "id", default="")),
            status=JobStatus.parse(_first(payload, "status", default="in_progress")),
            pending_changes=tuple(
                PendingChange.from_payload(c) for c in raw_changes if isinstance(c, dict)
            ),
            awaiting_kind=_first(metadata, "awaiting_kind", "awaitingKind"),
            error=_first(payload, "error", "error_message"),
            result=result,
            usage=JobUsage.from_payload((result or {}).get("usage")),
            session_id=_first(payload, "session_id", "sessionId"),
            progress=_coerce_int(_first(payload, "progress")),
            raw=payload,
        )

    @property
    def response_text(self) -> str | None:
        """The agent's prose reply, when it gave one."""
        value = (self.result or {}).get("response")
        return value if isinstance(value, str) else None

    @property
    def produced_nothing(self) -> bool:
        """Completed without proposing a single change.

        Either an honest report of no findings, or a turn the agent could not classify - which is
        billable anyway (BUGS.md #2). The run distinguishes the two by whether the reply reads as
        a refusal, and reports the second as a failure rather than a clean bill of health.
        """
        return self.status is JobStatus.COMPLETED and not self.pending_changes

    @property
    def is_continue_prompt(self) -> bool:
        """The job paused to ask whether to continue a large edit, not for an approval decision."""
        return self.status is JobStatus.AWAITING_APPROVAL and (
            (self.awaiting_kind or "").lower() in {"continue", "continue_prompt"}
        )


class DocumentUpload(BaseModel):
    """Result of uploading the document under lint.

    `chunk_ids` is the manifest every proposed change is validated against - a change targeting a
    chunk that is not in this set did not come from this document and is not applied.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    document_id: str | None = None
    version_id: str | None = None
    chunks_count: int | None = None
    html: str | None = None
    chunk_ids: tuple[str, ...] = ()
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, session_id: str) -> DocumentUpload:
        html = _first(payload, "html", "document_html", "content_html")
        return cls(
            session_id=str(_first(payload, "session_id", default=session_id)),
            document_id=_first(payload, "document_id", "documentId", "id"),
            version_id=_first(payload, "version_id", "versionId"),
            chunks_count=_first(payload, "chunks_count", "chunksCount"),
            html=html,
            chunk_ids=tuple(extract_chunk_ids(html)) if html else (),
            raw=payload,
        )


class AttachmentUpload(BaseModel):
    """What `POST /v1/attachments/upload-base64` actually returns.

    Note what is *not* here: an attachment id. The upload returns the id of the **processing job**,
    and the attachment id is issued asynchronously, appearing later under `ready_attachments` in
    the status response. Storing this `job_id` as though it were the attachment id is a silent
    error that only surfaces much later, so the type refuses to let you.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    session_id: str
    filename: str | None = None
    status: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, session_id: str) -> AttachmentUpload:
        return cls(
            job_id=str(_first(payload, "job_id", "jobId", default="")),
            session_id=str(_first(payload, "session_id", default=session_id)),
            filename=_first(payload, "filename", "name"),
            status=_first(payload, "status"),
            raw=payload,
        )


class Attachment(BaseModel):
    """A reference file that is ready for the AI to query - for this project, the style guide."""

    model_config = ConfigDict(frozen=True)

    attachment_id: str
    session_id: str | None = None
    filename: str | None = None
    chunks_count: int | None = None
    file_size: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, session_id: str | None = None) -> Attachment:
        return cls(
            attachment_id=str(_first(payload, "attachment_id", "attachmentId", "id", default="")),
            session_id=_first(payload, "session_id", default=session_id),
            filename=_first(payload, "filename", "name"),
            chunks_count=_coerce_int(_first(payload, "chunks_count", "chunksCount")),
            file_size=_coerce_int(_first(payload, "file_size", "fileSize")),
            raw=payload,
        )


class AttachmentStatus(BaseModel):
    """Parsed `GET /v1/attachments/status/{session_id}`.

    The response splits into two arrays rather than carrying a status per attachment: an item in
    `ready_attachments` has no `status` field at all - readiness is expressed by which array it is
    in. Code that polls a flat list for `status == "completed"` waits forever.
    """

    model_config = ConfigDict(frozen=True)

    ready: tuple[Attachment, ...] = ()
    processing: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, session_id: str) -> AttachmentStatus:
        ready_raw = payload.get("ready_attachments")
        if not isinstance(ready_raw, list):
            # Tolerate the flat shape the documentation describes, in case it ever appears.
            flat = payload.get("attachments")
            ready_raw = flat if isinstance(flat, list) else []
        jobs_raw = payload.get("processing_jobs")
        if not isinstance(jobs_raw, list):
            jobs_raw = []
        return cls(
            ready=tuple(
                Attachment.from_payload(item, session_id=session_id)
                for item in ready_raw
                if isinstance(item, dict)
            ),
            processing=tuple(item for item in jobs_raw if isinstance(item, dict)),
            raw=payload,
        )

    def find_ready(
        self, *, filename: str | None = None, job_id: str | None = None
    ) -> Attachment | None:
        """Resolve an upload to its ready attachment, by filename or originating job id."""
        if job_id is not None:
            for item in self.processing:
                if item.get("job_id") == job_id and item.get("attachment_id"):
                    for ready in self.ready:
                        if ready.attachment_id == item["attachment_id"]:
                            return ready
        if filename is not None:
            for ready in self.ready:
                if ready.filename == filename:
                    return ready
        return None

    def failure_for(self, job_id: str) -> str | None:
        for item in self.processing:
            if item.get("job_id") == job_id and str(item.get("status", "")).lower() in {
                "failed",
                "error",
            }:
                return str(item.get("error") or "attachment processing failed")
        return None


class Usage(BaseModel):
    """Operations consumed and remaining, sampled either side of a run to price it.

    Shape follows `GET /v1/agents/whoami`, which nests the counters under `quota`.
    """

    model_config = ConfigDict(frozen=True)

    operations_used: int | None = None
    operations_remaining: int | None = None
    monthly_limit: int | None = None
    plan: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Usage:
        quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
        nested = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        source = {**payload, **(nested or {}), **(quota or {})}
        return cls(
            operations_used=_coerce_int(
                _first(source, "used", "operations_used", "operationsUsed")
            ),
            operations_remaining=_coerce_int(
                _first(source, "remaining", "operations_remaining", "operationsRemaining")
            ),
            monthly_limit=_coerce_int(_first(source, "monthly_limit", "monthlyLimit", "limit")),
            plan=_first(source, "tier", "plan", "subscription_tier"),
            raw=payload,
        )


class JobUsage(BaseModel):
    """The `result.usage` block on a completed chat job.

    This, not `whoami`, is the truthful source for what a run cost:

    * `ops_charged` is the exact price of that one turn
    * `bucket_used` and `promotions` reveal promo allowances that `whoami` omits entirely
      (see BUGS.md #1 - `whoami` reported 500 operations while a promo bucket held 10,000)
    * `was_billable` reveals turns that were charged despite producing nothing (BUGS.md #2)
    """

    model_config = ConfigDict(frozen=True)

    ops_charged: int = 0
    was_billable: bool = False
    bucket_used: str | None = None
    monthly_remaining: int | None = None
    promo_remaining: int | None = None
    quota_exhausted: bool = False
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> JobUsage | None:
        if not isinstance(payload, dict):
            return None
        promos = payload.get("promotions")
        promo_remaining = None
        if isinstance(promos, list):
            totals = [
                _coerce_int(p.get("ops_remaining"))
                for p in promos
                if isinstance(p, dict) and _coerce_int(p.get("ops_remaining")) is not None
            ]
            if totals:
                promo_remaining = sum(t for t in totals if t is not None)
        return cls(
            ops_charged=_coerce_int(payload.get("ops_charged")) or 0,
            was_billable=bool(payload.get("was_billable", False)),
            bucket_used=payload.get("bucket_used"),
            monthly_remaining=_coerce_int(payload.get("monthly_remaining")),
            promo_remaining=promo_remaining,
            quota_exhausted=bool(payload.get("quota_exhausted", False)),
            raw=payload,
        )

    @property
    def total_remaining(self) -> int | None:
        """Operations actually available, monthly quota plus any promo bucket."""
        if self.monthly_remaining is None and self.promo_remaining is None:
            return None
        return (self.monthly_remaining or 0) + (self.promo_remaining or 0)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_chunk_ids(html: str | None) -> list[str]:
    """Pull `data-chunk-id` values out of parsed document HTML, in document order.

    Deliberately a regex rather than an HTML parser: this only needs the attribute values, the
    input is machine-generated, and adding a parser dependency to read one attribute is not worth
    it. Duplicates are collapsed, order is preserved.
    """
    import re

    if not html:
        return []
    seen: dict[str, None] = {}
    for match in re.finditer(r'data-chunk-id\s*=\s*["\']([^"\']+)["\']', html):
        seen.setdefault(match.group(1), None)
    return list(seen)
