"""A fully in-memory SuperDocs client for tests: no network, no API key.

Simulates just enough of the real API surface (upload/chat-async/poll/approve
/export) for the orchestrator's logic to be exercised end to end. It mirrors
the real contract's shapes (job status transitions, pending_changes,
change_id, document_changes.updated_html) closely enough that swapping in
the real SuperDocsClient requires no orchestrator code changes.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_SECTION_ID_RE = re.compile(r'data-section-id="([^"]+)"')
_CITATION_LINE_RE = re.compile(r"^- (.+)$", re.MULTILINE)
_SECTION_BLOCK_RE_TEMPLATE = r'(<div data-section-id="{}"[^>]*>)(.*?)(</div>)'


@dataclass
class _FakeJob:
    job_id: str
    session_id: str
    status: str
    pending_changes: List[Dict[str, Any]] = field(default_factory=list)
    section_id: Optional[str] = None
    proposed_new_section_html: Optional[str] = None


class FakeSuperDocsClient:
    """Reject-aware, second-parse-safe, no-network stand-in for SuperDocsClient."""

    def __init__(self):
        self.sessions: Dict[str, str] = {}  # session_id -> current document html
        self.jobs: Dict[str, _FakeJob] = {}
        self.fail_next_edit_for_section: Optional[str] = None
        self.no_op_sections: set = set()  # sections where the "model" proposes nothing

    def whoami(self) -> Dict[str, Any]:
        return {"account_id": "fake", "quota": {"remaining": 500, "monthly_limit": 500}}

    def upload_document(self, file_path: str, session_id: str) -> Dict[str, Any]:
        with open(file_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.sessions[session_id] = html
        return {"html": html, "session_id": session_id, "filename": file_path, "chunks_count": 1, "version_id": "v1"}

    def start_edit(
        self,
        session_id: str,
        message: str,
        document_html: Optional[str] = None,
        approval_mode: str = "ask_every_time",
        model_tier: Optional[str] = None,
    ) -> str:
        if document_html is not None:
            self.sessions[session_id] = document_html

        job_id = f"job-{uuid.uuid4().hex[:8]}"
        section_match = _SECTION_ID_RE.search(message)
        section_id = section_match.group(1) if section_match else None

        if section_id in self.no_op_sections:
            self.jobs[job_id] = _FakeJob(job_id, session_id, status="completed", section_id=section_id)
            return job_id

        current_html = self.sessions.get(session_id, "")
        block_re = re.compile(_SECTION_BLOCK_RE_TEMPLATE.format(re.escape(section_id or "")), re.DOTALL)
        m = block_re.search(current_html)
        old_inner = m.group(2) if m else ""

        citations = _CITATION_LINE_RE.findall(message)
        pending_changes = []
        for i, citation in enumerate(citations or ["(no citation)"]):
            new_inner = f"{old_inner} <span class='amended'>[AMENDED per: {citation[:60]}]</span>"
            pending_changes.append(
                {
                    "change_id": f"ch-{uuid.uuid4().hex[:8]}",
                    "operation": "edit",
                    "chunk_id": f"chunk-{section_id}-{i}",
                    "old_html": old_inner,
                    "new_html": new_inner,
                    "ai_explanation": f"Updated section per cited amendment: {citation[:80]}",
                }
            )

        self.jobs[job_id] = _FakeJob(
            job_id, session_id, status="awaiting_approval", pending_changes=pending_changes, section_id=section_id
        )
        return job_id

    def poll_job(self, job_id: str, timeout: float = 600.0, interval: float = 2.0) -> Dict[str, Any]:
        job = self.jobs[job_id]
        if job.status == "awaiting_approval":
            return {
                "job_id": job_id,
                "status": "awaiting_approval",
                "metadata": {"pending_changes": job.pending_changes},
            }
        if job.status == "completed":
            html = self.sessions.get(job.session_id, "")
            return {
                "job_id": job_id,
                "status": "completed",
                "result": {
                    "response": "No changes were necessary for this section.",
                    "document_changes": {"updated_html": html, "changes_summary": "no-op"},
                },
            }
        raise AssertionError(f"unexpected fake job status {job.status}")

    def approve(
        self,
        session_id: str,
        job_id: str,
        decisions: List[Dict[str, Any]],
        default_approved: bool = True,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        job = self.jobs[job_id]
        html = self.sessions.get(session_id, "")

        approved_ids = {d["change_id"] for d in decisions if d.get("approved")}
        for change in job.pending_changes:
            if change["change_id"] in approved_ids:
                html = html.replace(change["old_html"], change["new_html"], 1)

        self.sessions[session_id] = html
        job.status = "completed"
        return {"status": "ok"}

    def export(
        self,
        session_id: Optional[str] = None,
        html: Optional[str] = None,
        format: str = "docx",
        options: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        content = html if html is not None else self.sessions.get(session_id or "", "")
        return content.encode("utf-8")
