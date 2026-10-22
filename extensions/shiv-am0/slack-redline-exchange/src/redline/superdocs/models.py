from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED})

AWAITING_KIND_CONTINUE = "continue_prompt"

OPEN_MODE_REPLACE = "replace"
OPEN_MODE_NEW_FOCUSED = "new_focused"
OPEN_MODE_BACKGROUND = "background"
OPEN_MODES = frozenset({OPEN_MODE_REPLACE, OPEN_MODE_NEW_FOCUSED, OPEN_MODE_BACKGROUND})


@dataclass(frozen=True)
class PendingChange:
    change_id: str
    operation: str
    chunk_id: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str
    insert_after_chunk_id: str | None = None
    document_id: str | None = None


@dataclass(frozen=True)
class ApprovalDecision:
    change_id: str
    approved: bool
    feedback: str | None = None


@dataclass(frozen=True)
class ChatResult:
    response: str
    updated_html: str | None
    version_id: str | None
    changes_summary: str | None
    usage: dict[str, Any] = field(default_factory=dict)


def parse_pending_changes(value: Any) -> tuple[PendingChange, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        value = value.get("changes", [])
    items = list(value)
    parsed: list[PendingChange] = []
    for item in items:
        if isinstance(item, str):
            item = json.loads(item)
        parsed.append(
            PendingChange(
                change_id=str(item["change_id"]),
                operation=item.get("operation", "edit"),
                chunk_id=item.get("chunk_id"),
                old_html=item.get("old_html"),
                new_html=item.get("new_html"),
                ai_explanation=item.get("ai_explanation", ""),
                insert_after_chunk_id=item.get("insert_after_chunk_id"),
                document_id=item.get("document_id"),
            )
        )
    return tuple(parsed)


@dataclass(frozen=True)
class JobSnapshot:
    job_id: str
    status: str
    awaiting_kind: str | None
    pending_changes: tuple[PendingChange, ...]
    continue_prompt: dict[str, Any] | None
    result: ChatResult | None
    error: str | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_change_review(self) -> bool:
        return (
            self.status == STATUS_AWAITING_APPROVAL
            and self.awaiting_kind != AWAITING_KIND_CONTINUE
            and bool(self.pending_changes)
        )

    @property
    def is_continue_prompt(self) -> bool:
        return (
            self.status == STATUS_AWAITING_APPROVAL
            and self.awaiting_kind == AWAITING_KIND_CONTINUE
        )

    @classmethod
    def from_api(cls, job_id: str, payload: dict[str, Any]) -> JobSnapshot:
        meta = payload.get("metadata") or {}
        result_payload = payload.get("result")
        result = None
        if result_payload:
            changes = (result_payload.get("document_changes") or {}) or {}
            result = ChatResult(
                response=result_payload.get("response", ""),
                updated_html=changes.get("updated_html"),
                version_id=changes.get("version_id"),
                changes_summary=changes.get("changes_summary"),
                usage=result_payload.get("usage") or {},
            )
        return cls(
            job_id=job_id,
            status=payload.get("status", ""),
            awaiting_kind=meta.get("awaiting_kind"),
            pending_changes=parse_pending_changes(meta.get("pending_changes")),
            continue_prompt=meta.get("continue_prompt"),
            result=result,
            error=payload.get("error"),
            raw=payload,
        )


@dataclass(frozen=True)
class UploadResult:
    session_id: str
    filename: str
    chunks_count: int | None
    version_id: str | None
    document_id: str | None = None


@dataclass(frozen=True)
class SessionDocument:
    document_id: str
    title: str
    is_focused: bool
    sections_count: int | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> SessionDocument:
        return cls(
            document_id=str(payload.get("document_id") or payload.get("id") or ""),
            title=payload.get("title") or payload.get("filename") or "(untitled)",
            is_focused=bool(payload.get("is_focused") or payload.get("focused")),
            sections_count=payload.get("sections_count") or payload.get("chunks_count"),
        )


@dataclass(frozen=True)
class ExportResult:
    filename: str
    fmt: str
    content_b64: str | None
    download_url: str | None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    content_raw: bytes | None = field(default=None, repr=False)
    warnings: Any = None

    def content_bytes(self) -> bytes:
        import base64

        # The export endpoint may stream the file itself rather than wrapping it in
        # JSON; both shapes end up here so callers never care which one arrived.
        if self.content_raw is not None:
            return self.content_raw
        if self.content_b64 is not None:
            return base64.b64decode(self.content_b64)
        raise ValueError(
            "export returned a download_url instead of inline content; "
            f"fetch it separately: {self.download_url}"
        )


@dataclass(frozen=True)
class SessionJobSummary:
    job_id: str
    status: str
    awaiting_kind: str | None
