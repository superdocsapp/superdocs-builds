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
from typing import Any

import requests

BASE_URL = "https://api.superdocs.app"

logger = logging.getLogger(__name__)

# Status codes worth retrying: server-side/transient. 4xx (bad request,
# auth, etc.) are not retried -- retrying a malformed request just wastes
# operations and delays surfacing a real problem.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class SuperDocsError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ChatResult:
    session_id: str
    reply_text: str
    updated_html: str | None
    raw: dict[str, Any]


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = BASE_URL, session: requests.Session | None = None,
                 max_retries: int = 2, retry_backoff_s: float = 1.0, timeout_s: float = 60.0):
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.http = session or requests.Session()
        self.max_retries = max_retries
        self.retry_backoff_s = retry_backoff_s
        # Every request.* call below passes timeout=self.timeout_s. Without a
        # timeout, a stalled SuperDocs connection hangs the calling gunicorn
        # worker forever instead of failing an item -- in production that
        # takes down request capacity for every other user, not just this job.
        self.timeout_s = timeout_s

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # -- 1. draft / edit -----------------------------------------------------
    def chat(self, session_id: str, message: str, document_html: str | None = None) -> ChatResult:
        """Synchronous chat turn. Use for short single-turn drafting like
        this build's letters. For long/HITL work, use chat_async instead.

        Transient failures (429/5xx) are retried with exponential backoff
        up to `max_retries` times before raising -- a single rate limit
        blip or momentary 500 shouldn't be enough to mark an RFE item
        NOT ANSWERED. Non-retryable errors (4xx other than 429) raise
        immediately."""
        payload: dict[str, Any] = {"session_id": session_id, "message": message}
        if document_html is not None:
            payload["document_html"] = document_html

        attempt = 0
        while True:
            resp = self.http.post(f"{self.base_url}/v1/chat", headers=self._headers(), json=payload, timeout=self.timeout_s)
            try:
                self._raise_for_status(resp)
            except SuperDocsError as e:
                retryable = e.status_code in _RETRYABLE_STATUS_CODES
                if not retryable or attempt >= self.max_retries:
                    raise
                delay = self.retry_backoff_s * (2 ** attempt)
                logger.warning(
                    "SuperDocs chat call failed (status=%s, attempt=%d/%d); retrying in %.1fs",
                    e.status_code, attempt + 1, self.max_retries, delay,
                )
                time.sleep(delay)
                attempt += 1
                continue

            data = resp.json()
            changes = data.get("document_changes") or {}
            return ChatResult(
                session_id=session_id,
                reply_text=data.get("response", data.get("message", "")),
                updated_html=changes.get("updated_html"),
                raw=data,
            )

    def chat_async(self, session_id: str, message: str, approval_mode: str | None = None,
                    document_html: str | None = None) -> str:
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
    def approve_change(self, session_id: str, chunk_id: str | None = None, approved: bool = True,
                        feedback: str | None = None, changes: list[dict] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if changes is not None:
            payload["changes"] = changes
        else:
            payload["chunk_id"] = chunk_id
            payload["approved"] = approved
            if feedback:
                payload["feedback"] = feedback
        resp = self.http.post(
            f"{self.base_url}/v1/chat/{session_id}/approve", headers=self._headers(),
            json=payload, timeout=self.timeout_s,
        )
        self._raise_for_status(resp)
        return resp.json()

    # -- 3. export ------------------------------------------------------------
    def export(self, session_id: str, fmt: str = "docx", filename: str | None = None) -> bytes:
        payload: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if filename:
            payload["options"] = {"filename": filename}
        resp = self.http.post(
            f"{self.base_url}/v1/documents/export", headers=self._headers(),
            json=payload, timeout=self.timeout_s,
        )
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
            raise SuperDocsError(f"SuperDocs API error {resp.status_code}: {detail}", status_code=resp.status_code)
