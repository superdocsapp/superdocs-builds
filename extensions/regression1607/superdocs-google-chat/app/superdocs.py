"""SuperDocs REST client — the four calls Task 2's contract requires.

  upload_document  → POST /v1/documents/upload-base64
  chat_edit        → POST /v1/chat/async   (approval_mode="ask_every_time")
  approve_changes  → POST /v1/chat/{session_id}/approve
  export_document  → POST /v1/documents/export

We drive human-in-the-loop with the **polling** path (server-to-server), where a
job's ``metadata.pending_changes`` is already a JSON array. The double-parse trap
SuperDocs warns about only bites the SSE ``proposed_change_batch.content`` string;
``parse_pending_changes`` below handles either shape defensively.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://api.superdocs.app"


@dataclass
class ProposedChange:
    change_id: str
    operation: str  # edit | create | delete
    summary: str
    old_html: str | None
    new_html: str | None


class SuperDocsError(RuntimeError):
    pass


def parse_pending_changes(raw: Any) -> list[dict]:
    """Return the changes array whether it arrives as a list (polling) or a
    JSON-encoded string (SSE proposed_change_batch.content — the second-parse trap)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        obj = json.loads(raw)  # second parse
        return obj.get("changes", obj) if isinstance(obj, dict) else obj
    if isinstance(raw, dict):
        return raw.get("changes", [])
    return []


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, http: httpx.Client | None = None):
        if not api_key:
            raise SuperDocsError("SUPERDOCS_API_KEY is required")
        self._base = base_url.rstrip("/")
        # 300s: SuperDocs edits can silently take 30s–several minutes (their note).
        self._http = http or httpx.Client(timeout=300)
        self._headers = {"Authorization": f"Bearer {api_key}"}

    # 1) upload a document ----------------------------------------------------
    def upload_document(self, session_id: str, filename: str, content: str) -> dict:
        """Load ``content`` (HTML/text) as the session's active editable document."""
        payload = {
            "filename": filename,
            "file_base64": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "session_id": session_id,
        }
        return self._post_json("/v1/documents/upload-base64", payload)

    # 2) send an edit instruction --------------------------------------------
    def chat_edit(self, session_id: str, message: str, document_html: str | None = None) -> str:
        """Start an async, human-gated edit. Returns a job_id to poll."""
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": "ask_every_time",
        }
        if document_html is not None:
            body["document_html"] = document_html
        job = self._post_json("/v1/chat/async", body)
        return job["job_id"]

    def poll_job(self, job_id: str, *, interval: float = 2.0, max_wait: float = 300.0) -> dict:
        """Poll until the job leaves pending/in_progress. Returns the job dict."""
        waited = 0.0
        while True:
            job = self._get_json(f"/v1/jobs/{job_id}")
            status = job.get("status")
            if status in ("awaiting_approval", "completed", "failed", "cancelled"):
                return job
            if waited >= max_wait:
                raise SuperDocsError(f"job {job_id} did not settle within {max_wait}s")
            time.sleep(interval)
            waited += interval

    def pending_changes(self, job: dict) -> list[ProposedChange]:
        raw = (job.get("metadata") or {}).get("pending_changes")
        out = []
        for c in parse_pending_changes(raw):
            out.append(ProposedChange(
                change_id=c.get("change_id", ""),
                operation=c.get("operation", "edit"),
                summary=c.get("ai_explanation", ""),
                old_html=c.get("old_html"),
                new_html=c.get("new_html"),
            ))
        return out

    # 3) approve proposed changes --------------------------------------------
    def approve_changes(self, session_id: str, job_id: str, decisions: list[dict]) -> dict:
        """decisions: [{"change_id": ..., "approved": true|false, "feedback"?: ...}]."""
        body = {"job_id": job_id, "approved": True, "changes": decisions}
        return self._post_json(f"/v1/chat/{session_id}/approve", body)

    # 4) export the finished file --------------------------------------------
    def export_document(self, session_id: str, fmt: str = "docx") -> bytes:
        r = self._http.post(
            f"{self._base}/v1/documents/export",
            headers={**self._headers, "Content-Type": "application/json"},
            json={"session_id": session_id, "format": fmt},
        )
        self._raise(r)
        return r.content

    def download_url(self, session_id: str, fmt: str = "docx") -> dict:
        """Real, short-lived (~15 min) signed GET URL for the session's document —
        an honest link we can put on a Chat card instead of a fabricated one.
        Returns the ``{download_url, filename, expires_at, ...}`` dict."""
        return self._post_json("/v1/downloads", {"session_id": session_id, "format": fmt})

    # multi-document sessions (tabs) --------------------------------------------
    def session_documents(self, session_id: str) -> list[dict]:
        """Roster of open documents in the session (each with a durable_document_id)."""
        return self._get_json(f"/v1/sessions/{session_id}/documents").get("documents", [])

    def focused_durable_id(self, session_id: str) -> str | None:
        """Durable File id of the focused document — the id another session can
        re-open as a tab. Null until the document has been saved."""
        for d in self.session_documents(session_id):
            if d.get("focused"):
                return d.get("durable_document_id")
        return None

    def open_documents(self, session_id: str, document_ids: list[str]) -> dict:
        """Open saved durable documents into ``session_id`` as tabs (shared, not
        copied). Used to draft a new document with a prior one open as reference."""
        return self._post_json(f"/v1/sessions/{session_id}/documents/open",
                               {"document_ids": document_ids})

    # helpers -----------------------------------------------------------------
    def _post_json(self, path: str, body: dict) -> dict:
        r = self._http.post(
            f"{self._base}{path}",
            headers={**self._headers, "Content-Type": "application/json"},
            json=body,
        )
        self._raise(r)
        return r.json()

    def _get_json(self, path: str) -> dict:
        r = self._http.get(f"{self._base}{path}", headers=self._headers)
        self._raise(r)
        return r.json()

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if r.status_code >= 400:
            raise SuperDocsError(f"SuperDocs {r.status_code}: {r.text[:300]}")
