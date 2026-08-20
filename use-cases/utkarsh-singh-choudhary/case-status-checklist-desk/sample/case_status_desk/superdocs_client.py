"""
Minimal SuperDocs REST client -- just the operations this build needs:
create/continue a chat session (draft the letter), poll an async job,
approve pending changes, and export the final file.

Deliberately thin and dependency-light (just `requests`) so it's easy
to read, easy to mock in tests, and easy to swap for the MCP surface
later if desired.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

BASE_URL = "https://api.superdocs.app"


class SuperDocsError(RuntimeError):
    pass


@dataclass
class ChatResult:
    session_id: str
    reply_text: str
    updated_html: Optional[str]
    raw: dict[str, Any]


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, session: Optional[requests.Session] = None):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # -- 1. draft / edit -----------------------------------------------------
    def chat(self, session_id: str, message: str, document_html: Optional[str] = None) -> ChatResult:
        """Synchronous chat turn. Use for short single-turn drafting like
        this build's letters. For long/HITL work, use chat_async instead."""
        payload: dict[str, Any] = {"session_id": session_id, "message": message}
        if document_html is not None:
            payload["document_html"] = document_html
        resp = self.http.post(f"{self.base_url}/v1/chat", headers=self._headers(), json=payload)
        self._raise_for_status(resp)
        data = resp.json()
        changes = data.get("document_changes") or {}
        return ChatResult(
            session_id=session_id,
            reply_text=data.get("response", data.get("message", "")),
            updated_html=changes.get("updated_html"),
            raw=data,
        )

    def chat_async(self, session_id: str, message: str, approval_mode: Optional[str] = None,
                    document_html: Optional[str] = None) -> str:
        """Start a long-running / HITL job. Returns job_id."""
        payload: dict[str, Any] = {"session_id": session_id, "message": message}
        if approval_mode:
            payload["approval_mode"] = approval_mode
        if document_html is not None:
            payload["document_html"] = document_html
        resp = self.http.post(f"{self.base_url}/v1/chat/async", headers=self._headers(), json=payload)
        self._raise_for_status(resp)
        return resp.json()["job_id"]

    def get_job(self, job_id: str) -> dict[str, Any]:
        resp = self.http.get(f"{self.base_url}/v1/jobs/{job_id}", headers=self._headers())
        self._raise_for_status(resp)
        return resp.json()

    def wait_for_job(self, job_id: str, terminal_statuses=("completed", "failed", "cancelled", "awaiting_approval"),
                      timeout_s: float = 600, poll_interval_s: float = 2.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while True:
            job = self.get_job(job_id)
            if job.get("status") in terminal_statuses:
                return job
            if time.monotonic() > deadline:
                raise SuperDocsError(f"Timed out waiting for job {job_id}")
            time.sleep(poll_interval_s)

    # -- 2. human/machine approval gate --------------------------------------
    def approve_change(self, session_id: str, chunk_id: Optional[str] = None, approved: bool = True,
                        feedback: Optional[str] = None, changes: Optional[list[dict]] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if changes is not None:
            payload["changes"] = changes
        else:
            payload["chunk_id"] = chunk_id
            payload["approved"] = approved
            if feedback:
                payload["feedback"] = feedback
        resp = self.http.post(f"{self.base_url}/v1/chat/{session_id}/approve", headers=self._headers(), json=payload)
        self._raise_for_status(resp)
        return resp.json()

    # -- 3. export ------------------------------------------------------------
    def export(self, session_id: str, fmt: str = "docx", filename: Optional[str] = None) -> bytes:
        payload: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if filename:
            payload["options"] = {"filename": filename}
        resp = self.http.post(f"{self.base_url}/v1/documents/export", headers=self._headers(), json=payload)
        self._raise_for_status(resp)
        return resp.content

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            raise SuperDocsError(f"SuperDocs API error {resp.status_code}: {detail}")
