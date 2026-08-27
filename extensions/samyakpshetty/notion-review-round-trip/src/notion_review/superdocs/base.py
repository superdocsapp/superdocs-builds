"""The SuperDocs client protocol and the one place the double-parse gotcha is handled."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from notion_review.superdocs.models import (
    ApprovalDecision,
    ApproveResult,
    ChunkDiff,
    ExportResult,
    Job,
    UploadResult,
)


class SuperDocsError(Exception):
    """A SuperDocs API call failed."""


def parse_pending_changes(metadata: Mapping[str, Any]) -> list[ChunkDiff]:
    """Extract proposed changes from async job metadata.

    SuperDocs returns ``metadata.pending_changes`` as a JSON-encoded **string**, not an
    object — so it needs a *second* ``json.loads``. Missing that is the single most common
    reason integrators see empty diff cards with every field ``undefined``. We do it once,
    here, for both the live and fake clients, and tolerate the already-decoded form too.
    """
    raw = metadata.get("pending_changes")
    if raw is None:
        return []
    if isinstance(raw, str):
        if not raw.strip():
            return []
        raw = json.loads(raw)  # the crucial second parse
    if not isinstance(raw, list):
        return []
    return [ChunkDiff.model_validate(item) for item in raw]


@runtime_checkable
class SuperDocsClient(Protocol):
    """The four core calls (plus the async job poll the gate needs), as a typed seam.

    Both :class:`~notion_review.superdocs.fake.FakeSuperDocsClient` and the live HTTP client
    satisfy this. Everything above this line is provider-agnostic.
    """

    def upload_document(self, *, document_html: str, session_id: str) -> UploadResult: ...

    def chat_async(
        self,
        *,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
    ) -> str:
        """Start an async edit; returns a ``job_id`` to poll."""
        ...

    def get_job(self, job_id: str) -> Job: ...

    def approve(
        self, *, session_id: str, decisions: list[ApprovalDecision], job_id: str = ""
    ) -> ApproveResult: ...

    def export(self, *, session_id: str, fmt: str = "docx") -> ExportResult: ...
