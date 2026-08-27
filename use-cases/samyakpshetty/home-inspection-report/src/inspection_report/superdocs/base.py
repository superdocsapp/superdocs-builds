"""The SuperDocs client protocol, and the parsing gotchas handled in exactly one place.

Everything above this seam is provider-agnostic: the deterministic fake and the live HTTP
client both satisfy this protocol, so the whole application — including the web interface —
runs with no API key at all.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from inspection_report.superdocs.models import (
    ApprovalDecision,
    ApproveResult,
    ChunkDiff,
    ExportOptions,
    ExportResult,
    ImageUpload,
    Job,
    JobStatus,
    TemplateRef,
    UploadResult,
    Usage,
)

# Images: PNG/JPEG/WebP/GIF/SVG, 10 MB decoded. The fake enforces these too — a fake that is
# more permissive than the service hides exactly the bugs it exists to catch.
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml"}
)


class SuperDocsError(Exception):
    """A SuperDocs API call failed."""


class SessionBusyError(SuperDocsError):
    """The session holds a pending proposal set.

    409 ``session_busy`` conflates "still processing" with "proposals are pending approval".
    The second never clears by waiting, so callers gate and apply a batch before sending the
    next rather than retrying into a wall.
    """


def parse_pending_changes(payload: Mapping[str, Any]) -> list[ChunkDiff]:
    """Pull proposed changes out of a job, wherever this API decided to put them.

    Two documented traps, both handled here so neither client has to remember:

    * ``pending_changes`` arrives as a JSON-encoded **string** and needs a second parse.
      Missing that is the single most common reason integrators see diff cards where every
      field reads as undefined.
    * On a completed job the changes live under ``result.document_changes``, while an
      awaiting-approval job carries them in ``metadata``. Both are checked.
    """
    raw: Any = None
    for holder in (
        (payload.get("result") or {}).get("document_changes") or {},
        payload.get("metadata") or {},
        payload,
    ):
        if isinstance(holder, Mapping):
            for key in ("pending_changes", "chunk_diffs", "changes"):
                if holder.get(key):
                    raw = holder[key]
                    break
        if raw is not None:
            break

    if raw is None:
        return []
    if isinstance(raw, str):
        if not raw.strip():
            return []
        raw = json.loads(raw)  # the crucial second parse
    if not isinstance(raw, list):
        return []
    return [ChunkDiff.model_validate(item) for item in raw]


def parse_document_html(payload: Mapping[str, Any]) -> str | None:
    """Find the document on a job.

    A completed job reports ``document_html: null`` at the top level and puts the real
    content at ``result.document_changes.updated_html``. Verified against the live API.
    """
    changes = (payload.get("result") or {}).get("document_changes") or {}
    if isinstance(changes, Mapping):
        html = changes.get("updated_html")
        if isinstance(html, str) and html:
            return html
    top = payload.get("document_html")
    return top if isinstance(top, str) and top else None


def parse_usage(payload: Mapping[str, Any]) -> Usage | None:
    raw = (payload.get("result") or {}).get("usage") or payload.get("usage")
    return Usage.model_validate(raw) if isinstance(raw, Mapping) else None


def parse_status(value: Any) -> JobStatus:
    try:
        return JobStatus(value)
    except (ValueError, TypeError):
        return JobStatus.PROCESSING


@runtime_checkable
class SuperDocsClient(Protocol):
    """Everything this build asks of SuperDocs, as one typed seam.

    The four calls the task names as the minimum contract — upload, chat, approve, export —
    plus the job poll the human gate needs, and the image and template surfaces this card
    names explicitly.
    """

    # --- the minimum contract ------------------------------------------------------
    def upload_document(self, *, document_html: str, session_id: str) -> UploadResult: ...

    def chat_async(
        self,
        *,
        session_id: str,
        message: str,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
        thinking_depth: str = "balanced",
    ) -> str:
        """Start an async edit; returns a ``job_id`` to poll."""
        ...

    def get_job(self, job_id: str) -> Job: ...

    def approve(
        self, *, session_id: str, decisions: list[ApprovalDecision], job_id: str
    ) -> ApproveResult:
        """Relay a batch of decisions. **One call per job** — approving closes it."""
        ...

    def export(
        self, *, session_id: str, fmt: str = "docx", options: ExportOptions | None = None
    ) -> ExportResult: ...

    # --- the surfaces this card names ----------------------------------------------
    def upload_image(
        self, *, data: bytes, filename: str, content_type: str = "image/png"
    ) -> ImageUpload: ...

    def upload_template(self, *, data: bytes, filename: str) -> TemplateRef: ...

    def list_templates(self) -> list[TemplateRef]: ...

    def delete_template(self, template_id: str) -> None: ...

    def ops_remaining(self) -> int | None:
        """Operations left, read without spending one. ``None`` when there is no budget."""
        ...

    # --- operational ---------------------------------------------------------------
    def continue_job(self, *, session_id: str, job_id: str, keep_going: bool) -> None:
        """Answer a large edit that paused and asked whether to carry on."""
        ...

    def close(self) -> None: ...
