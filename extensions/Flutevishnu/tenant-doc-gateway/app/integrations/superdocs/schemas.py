"""Lightweight value objects for SuperDocs responses we care about.

We intentionally do NOT model SuperDocs' entire surface — only the fields our
four-call flow depends on — so upstream additions don't break us.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class UploadResult:
    document_id: str
    session_id: str
    ops_cost: float = 0.0


@dataclass
class JobResult:
    job_id: str
    status: str  # pending | in_progress | awaiting_approval | completed | failed
    session_id: str = ""
    document_html: str | None = None
    # Already double-parsed into a list of change dicts (see client.parse_changes).
    pending_changes: list[dict] = field(default_factory=list)
    ops_cost: float = 0.0
    raw: dict = field(default_factory=dict)


@dataclass
class ExportResult:
    download_url: str | None = None
    content_base64: str | None = None
    inline_content: str | None = None
    ops_cost: float = 0.0  # Exports are free in SuperDocs, but we track anyway.
