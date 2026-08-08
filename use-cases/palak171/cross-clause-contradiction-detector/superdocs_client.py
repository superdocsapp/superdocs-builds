"""
Thin, typed wrapper around the four SuperDocs REST calls this build needs:
upload, chat (detect + edit), approve (the Review surface), export. Nothing
here reimplements SuperDocs — every edit is made by SuperDocs' own AI; this
client only shapes the requests and unwraps the responses.

Two documented gotchas from docs.superdocs.app/llms-full.txt, handled once,
here, instead of at every call site:

1. HITL proposed-change content is delivered double-encoded in the streaming
   path (`envelope.content` is itself a JSON string needing a second
   `json.loads`). We sidestep that entirely by using the polling path
   (`GET /v1/jobs/{job_id}`) instead of SSE — `job["metadata"]["pending_changes"]`
   there is already a plain list, no double-parse needed. Documented as a
   deliberate choice, not an oversight: see README "Why polling, not SSE".

2. Long-running edits or deep model settings can sit at status="in_progress"
   for up to several minutes with no intermediate signal — `wait_for_job`
   treats that as normal, not a hang, and only raises on an actual timeout.
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

BASE_URL = "https://api.superdocs.app/v1"


class SuperDocsError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"SuperDocs API error {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class JobTimeout(Exception):
    pass


@dataclass
class ProposedChange:
    change_id: str
    chunk_id: str
    operation: str
    old_html: str
    new_html: str
    ai_explanation: str

    @classmethod
    def from_dict(cls, d: dict) -> "ProposedChange":
        return cls(
            change_id=d["change_id"],
            chunk_id=d.get("chunk_id", ""),
            operation=d.get("operation", ""),
            old_html=d.get("old_html", ""),
            new_html=d.get("new_html", ""),
            ai_explanation=d.get("ai_explanation", ""),
        )


@dataclass
class ExportResult:
    content: bytes
    filename: str
    content_type: str
    warnings: list[dict]


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: float = 60.0):
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = httpx.Client(base_url=base_url, headers=self._headers, timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _raise_for_status(self, response: httpx.Response):
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise SuperDocsError(response.status_code, str(detail))

    # ---- 1. upload -----------------------------------------------------

    def upload_document(self, file_path: str | Path, session_id: str) -> dict:
        """POST /v1/documents/upload — loads a contract as the active, editable document."""
        file_path = Path(file_path)
        with open(file_path, "rb") as f:
            response = self._client.post(
                "/documents/upload",
                files={"file": (file_path.name, f)},
                data={"session_id": session_id},
            )
        self._raise_for_status(response)
        return response.json()

    # ---- 2. chat (detection, and edit proposals) ------------------------

    def chat(self, message: str, session_id: str, document_html: str | None = None,
              model_tier: str | None = None, thinking_depth: str | None = None) -> dict:
        """POST /v1/chat — synchronous, read-only-safe when the instruction doesn't ask for edits.
        Used here for the detection pass (the 'chat'/'search' surface): no approval_mode means
        no proposed edits are generated, just an analysis in `response`."""
        payload: dict = {"message": message, "session_id": session_id}
        if document_html is not None:
            payload["document_html"] = document_html
        if model_tier:
            payload["model_tier"] = model_tier
        if thinking_depth:
            payload["thinking_depth"] = thinking_depth
        response = self._client.post("/chat", json=payload)
        self._raise_for_status(response)
        return response.json()

    def start_edit(self, message: str, session_id: str, document_html: str | None = None,
                    model_tier: str | None = None, thinking_depth: str | None = None) -> dict:
        """POST /v1/chat/async with approval_mode='ask_every_time' — the Review surface.
        Returns {"job_id": ...}; poll with wait_for_job."""
        payload: dict = {
            "message": message, "session_id": session_id, "approval_mode": "ask_every_time",
        }
        if document_html is not None:
            payload["document_html"] = document_html
        if model_tier:
            payload["model_tier"] = model_tier
        if thinking_depth:
            payload["thinking_depth"] = thinking_depth
        response = self._client.post("/chat/async", json=payload)
        self._raise_for_status(response)
        return response.json()

    def get_job(self, job_id: str) -> dict:
        response = self._client.get(f"/jobs/{job_id}")
        self._raise_for_status(response)
        return response.json()

    def wait_for_job(self, job_id: str, poll_interval: float = 2.0, timeout: float = 600.0) -> dict:
        """Polls until status is one of completed/failed/awaiting_approval.
        Returns the job dict at that point; caller decides what to do next."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id)
            if job["status"] in ("completed", "failed", "awaiting_approval", "cancelled"):
                return job
            if time.monotonic() > deadline:
                raise JobTimeout(f"job {job_id} still '{job['status']}' after {timeout}s")
            time.sleep(poll_interval)

    def pending_changes(self, job: dict) -> list[ProposedChange]:
        changes = job.get("metadata", {}).get("pending_changes", [])
        return [ProposedChange.from_dict(c) for c in changes]

    # ---- 3. approve (the Review surface, item by item) -------------------

    def approve_changes(self, session_id: str, job_id: str,
                          decisions: list[tuple[str, bool, str | None]]) -> dict:
        """POST /v1/chat/{session_id}/approve. `decisions` is [(change_id, approved, feedback)].
        Rejecting one change never discards the others — each is its own entry in `changes`."""
        changes = []
        for change_id, approved, feedback in decisions:
            entry = {"change_id": change_id, "approved": approved}
            if feedback:
                entry["feedback"] = feedback
            changes.append(entry)
        payload = {"job_id": job_id, "approved": True, "changes": changes}
        response = self._client.post(f"/chat/{session_id}/approve", json=payload)
        self._raise_for_status(response)
        return response.json()

    # ---- 4. export -------------------------------------------------------

    def export_document(self, session_id: str, format: str = "docx",
                          options: dict | None = None) -> ExportResult:
        """POST /v1/documents/export — free, does not consume operations."""
        payload: dict = {"session_id": session_id, "format": format}
        if options:
            payload["options"] = options
        response = self._client.post("/documents/export", json=payload)
        self._raise_for_status(response)

        filename = "export"
        disposition = response.headers.get("content-disposition", "")
        if "filename=" in disposition:
            filename = disposition.split("filename=")[-1].strip('"; ')

        warnings = []
        warnings_header = response.headers.get("x-export-warnings")
        if warnings_header:
            warnings = json.loads(base64.b64decode(warnings_header))

        return ExportResult(
            content=response.content,
            filename=filename,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            warnings=warnings,
        )
