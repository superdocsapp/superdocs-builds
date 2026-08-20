"""A stand-in for the SuperDocs API so the flow is testable with no key and no
network. It records what it was asked to do, which is how the tests assert that
denied changes were actually denied."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from stylefix.client import Usage


@dataclass
class FakeClient:
    html: str
    proposals: dict[str, list[dict]] = field(default_factory=dict)
    approvals: list[tuple[str, bool, str | None]] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    attached: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    readiness_checks: int = 0
    waits: list = field(default_factory=list)

    def init_session(self, session_id: str) -> dict:
        return {"session_id": session_id}

    def upload_document(self, path, session_id: str) -> dict:
        return {"html": self.html}

    def upload_attachment(self, path, session_id: str) -> dict:
        self.attached.append(str(path))
        return {"attachment_id": "a1"}

    def attachment_ready(self, session_id: str, **kw) -> dict:
        self.readiness_checks += 1
        return {"status": "ready"}

    def chat_async(self, session_id: str, message: str, **options) -> dict:
        return self.chat(session_id, message, **options)

    def chat(self, session_id: str, message: str, **options) -> dict:
        self.usage.record("chat")
        guide = self.attached[-1] if self.attached else ""
        key = next((k for k in self.proposals if k in guide), None)
        return {"job_id": "job-1", "pending_changes": self.proposals.get(key, [])}

    def wait_for_job(self, session_id: str, job_id: str, **kw) -> dict:
        self.waits.append(kw.get("require_completed", False))
        return {"job_id": job_id, "status": "completed"}

    def approve(self, session_id: str, job_id: str, approved: bool,
                change_id: str | None = None, feedback: str | None = None) -> dict:
        self.approvals.append((change_id or "", approved, feedback))
        return {"ok": True}

    def export(self, session_id: str, fmt: str = "docx", filename: str | None = None) -> dict:
        self.exports.append(fmt)
        return {"format": fmt, "url": "https://example.invalid/out." + fmt}
