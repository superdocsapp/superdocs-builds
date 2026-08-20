"""
Minimal SuperDocs REST client -- just the operations this build needs:
create/continue a chat session (draft the letter), poll an async job,
approve pending changes, and export the final file.

Deliberately thin and dependency-light (just `requests`) so it's easy
to read, easy to mock in tests, and easy to swap for the MCP surface
later if desired.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

BASE_URL = "https://api.superdocs.app"
DEFAULT_TIMEOUT_S = 30

logger = logging.getLogger("case_status_desk.superdocs_client")


class SuperDocsError(RuntimeError):
    pass


class SuperDocsTransientError(SuperDocsError):
    """5xx / network-level failure -- safe to retry."""


class SuperDocsAuthError(SuperDocsError):
    """401/403 -- bad or revoked API key. Not retryable."""


@dataclass
class ChatResult:
    session_id: str
    reply_text: str
    updated_html: Optional[str]
    raw: dict[str, Any]


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, session: Optional[requests.Session] = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http = session or requests.Session()
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type((SuperDocsTransientError, requests.ConnectionError, requests.Timeout)),
    )
    def _post(self, path: str, payload: dict[str, Any]) -> requests.Response:
        try:
            resp = self.http.post(f"{self.base_url}{path}", headers=self._headers(),
                                   json=payload, timeout=self.timeout_s)
        except (requests.ConnectionError, requests.Timeout) as exc:
            logger.warning("SuperDocs network error on %s, will retry: %s", path, exc)
            raise
        self._raise_for_status(resp)
        return resp

    # -- 1. draft / edit -----------------------------------------------------
    def chat(self, session_id: str, message: str, document_html: Optional[str] = None) -> ChatResult:
        """Synchronous chat turn. Use for short single-turn drafting like
        this build's letters. For long/HITL work, use chat_async instead."""
        payload: dict[str, Any] = {"session_id": session_id, "message": message}
        if document_html is not None:
            payload["document_html"] = document_html
        resp = self._post("/v1/chat", payload)
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
        resp = self.http.post(f"{self.base_url}/v1/chat/async", headers=self._headers(), json=payload, timeout=self.timeout_s)
        self._raise_for_status(resp)
        return resp.json()["job_id"]

    def get_job(self, job_id: str) -> dict[str, Any]:
        resp = self.http.get(f"{self.base_url}/v1/jobs/{job_id}", headers=self._headers(), timeout=self.timeout_s)
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
        resp = self.http.post(f"{self.base_url}/v1/chat/{session_id}/approve", headers=self._headers(), json=payload, timeout=self.timeout_s)
        self._raise_for_status(resp)
        return resp.json()

    # -- 3. export ------------------------------------------------------------
    def export(self, session_id: str, fmt: str = "docx", filename: Optional[str] = None) -> bytes:
        payload: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if filename:
            payload["options"] = {"filename": filename}
        resp = self.http.post(f"{self.base_url}/v1/documents/export", headers=self._headers(), json=payload, timeout=self.timeout_s)
        self._raise_for_status(resp)
        return resp.content

    # -- Files (durable documents) -------------------------------------------
    def list_documents(self, limit: int = 50) -> list[dict[str, Any]]:
        """List durable Files (documents persisted across sessions), most
        recently updated first. Metadata only -- no HTML body."""
        resp = self.http.get(f"{self.base_url}/v1/documents", headers=self._headers(),
                              params={"limit": limit}, timeout=self.timeout_s)
        self._raise_for_status(resp)
        return resp.json()

    def get_document_detail(self, document_id: str, include_html: bool = False) -> dict[str, Any]:
        resp = self.http.get(f"{self.base_url}/v1/documents/{document_id}", headers=self._headers(),
                              params={"include_html": str(include_html).lower()}, timeout=self.timeout_s)
        self._raise_for_status(resp)
        return resp.json()

    def rename_document(self, document_id: str, title: str) -> dict[str, Any]:
        resp = self.http.patch(f"{self.base_url}/v1/documents/{document_id}", headers=self._headers(),
                                json={"title": title}, timeout=self.timeout_s)
        self._raise_for_status(resp)
        return resp.json()

    def archive_document(self, document_id: str, force: bool = False) -> dict[str, Any]:
        """Soft-delete a durable File (recoverable ~30 days). Returns 409
        document_in_use if the File is open in another session and force
        is not set."""
        resp = self.http.delete(f"{self.base_url}/v1/documents/{document_id}", headers=self._headers(),
                                 params={"force": str(force).lower()}, timeout=self.timeout_s)
        self._raise_for_status(resp)
        return resp.json()


    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text
        if resp.status_code in (401, 403):
            raise SuperDocsAuthError(f"SuperDocs auth error {resp.status_code}: {detail}")
        if resp.status_code >= 500:
            raise SuperDocsTransientError(f"SuperDocs server error {resp.status_code}: {detail}")
        raise SuperDocsError(f"SuperDocs API error {resp.status_code}: {detail}")
