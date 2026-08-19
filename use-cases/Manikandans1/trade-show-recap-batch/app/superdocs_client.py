"""Client for SuperDocs' real, documented REST contract, used for the
four-call sequence this build needs: upload the branded template, edit
it with an exact substitution instruction, get every change approved,
export.

Earlier version of this file was written against a *guessed* schema
(POST /documents, POST /documents/{id}/chat, POST /documents/{id}/approve,
GET /documents/{id}/export) because docs.superdocs.app was reported
unreachable from the original build environment. None of those endpoints
exist on the real API. This version is written directly against the
documented endpoints — see README "How this matches the real API" for
the endpoint-by-endpoint mapping, and
extensions/object-storage-pipeline/app/superdocs_client.py for the same
fix applied to this round's other assigned build (that file has the more
detailed docstring on the async/poll/approve sequence, since this build
doesn't need the streaming half of it).

Unlike the object-storage-pipeline build, this one does not need
streaming: recap documents and templates are small (a few KB of text),
so plain buffered requests are the right level of complexity here —
reaching for streaming machinery a document this size will never need
would be over-engineering, not rigor.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("superdocs_client")


class SuperDocsError(Exception):
    def __init__(self, message: str, status_code: int | None = None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class UploadInfo:
    session_id: str
    chunks_count: int | None = None
    version_id: str | None = None


@dataclass
class ChatResult:
    response_text: str
    updated_html: str | None
    changes_summary: str | None
    monthly_used: int | None = None
    monthly_remaining: int | None = None
    was_billable: bool | None = None


class SuperDocsClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        http_client: httpx.Client | None = None,
        default_approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        max_retries: int = 5,
        retry_base_delay_seconds: float = 1.0,
        request_timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 2.0,
        max_wait_seconds: float = 300.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._default_approval_mode = default_approval_mode
        self._model_tier = model_tier
        self._thinking_depth = thinking_depth
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay_seconds
        self._poll_interval = poll_interval_seconds
        self._max_wait_seconds = max_wait_seconds
        self._client = http_client or httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=request_timeout_seconds
        )

    # ------------------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._base_url}{path}"
        attempt = 0
        while True:
            attempt += 1
            response = self._client.request(method, url, **kwargs)
            if response.status_code == 429 and attempt <= self._max_retries:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after_header) if retry_after_header else None
                except ValueError:
                    delay = None
                if delay is None:
                    delay = self._retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "429 from %s %s — retrying in %.1fs (attempt %d/%d)",
                    method, path, delay, attempt, self._max_retries,
                )
                time.sleep(delay)
                continue
            if response.status_code >= 500 and attempt <= self._max_retries:
                delay = self._retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "%s from %s %s — retrying in %.1fs (attempt %d/%d)",
                    response.status_code, method, path, delay, attempt, self._max_retries,
                )
                time.sleep(delay)
                continue
            return response

    @staticmethod
    def _raise_for_error(response: httpx.Response, action: str) -> None:
        if response.status_code < 400:
            return
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise SuperDocsError(
            f"{action} failed: HTTP {response.status_code} {detail}",
            status_code=response.status_code,
            body=detail,
        )

    # ------------------------------------------------------------------
    # Upload — POST /v1/documents/upload. Templates here are small text
    # files, so a plain buffered multipart request (httpx's own `files=`
    # handling) is the right level of complexity — no need for the
    # hand-rolled streaming encoder the object-storage-pipeline build
    # uses for large, unpredictable-size source files.
    # ------------------------------------------------------------------
    def upload_document(self, content: bytes, filename: str, session_id: str) -> UploadInfo:
        response = self._client.post(
            f"{self._base_url}/v1/documents/upload",
            data={"session_id": session_id},
            files={"file": (filename, content, "text/plain")},
        )
        self._raise_for_error(response, "POST /v1/documents/upload")
        payload = response.json()
        return UploadInfo(
            session_id=payload.get("session_id", session_id),
            chunks_count=payload.get("chunks_count"),
            version_id=payload.get("version_id"),
        )

    # ------------------------------------------------------------------
    # Edit (+ approve) — same two documented modes as the
    # object-storage-pipeline build; see that file's docstring for the
    # full async/poll/approve/continue sequence detail.
    # ------------------------------------------------------------------
    def edit_document(
        self, session_id: str, instruction: str, approval_mode: str | None = None
    ) -> ChatResult:
        mode = approval_mode or self._default_approval_mode
        if mode == "approve_all":
            return self._edit_sync_approve_all(session_id, instruction)
        if mode == "ask_every_time":
            return self._edit_async_with_review(session_id, instruction)
        raise ValueError(f"unknown approval_mode: {mode!r}")

    def _chat_body(self, session_id: str, instruction: str, approval_mode: str) -> dict:
        body: dict = {
            "message": instruction,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }
        if self._model_tier:
            body["model_tier"] = self._model_tier
        if self._thinking_depth:
            body["thinking_depth"] = self._thinking_depth
        return body

    def _edit_sync_approve_all(self, session_id: str, instruction: str) -> ChatResult:
        response = self._request(
            "POST", "/v1/chat", json=self._chat_body(session_id, instruction, "approve_all")
        )
        self._raise_for_error(response, "POST /v1/chat")
        return self._chat_result_from_payload(response.json())

    def _edit_async_with_review(self, session_id: str, instruction: str) -> ChatResult:
        start = self._request(
            "POST", "/v1/chat/async", json=self._chat_body(session_id, instruction, "ask_every_time")
        )
        self._raise_for_error(start, "POST /v1/chat/async")
        job_id = start.json()["job_id"]

        deadline = time.monotonic() + self._max_wait_seconds
        while True:
            if time.monotonic() > deadline:
                raise SuperDocsError(f"job {job_id} did not settle within {self._max_wait_seconds}s")

            job_resp = self._request("GET", f"/v1/jobs/{job_id}")
            self._raise_for_error(job_resp, f"GET /v1/jobs/{job_id}")
            job = job_resp.json()
            status = job.get("status")

            if status == "completed":
                return self._chat_result_from_payload(job.get("result") or {})
            if status == "failed":
                raise SuperDocsError(f"job {job_id} failed: {job.get('error')}")
            if status == "cancelled":
                raise SuperDocsError(f"job {job_id} was cancelled")
            if status == "awaiting_approval":
                metadata = job.get("metadata") or {}
                if metadata.get("awaiting_kind") == "continue_prompt":
                    self._continue_job(session_id, job_id, keep_going=True)
                else:
                    pending = metadata.get("pending_changes") or []
                    if pending:
                        self._approve_all_pending(session_id, job_id, pending)

            time.sleep(self._poll_interval)

    def _approve_all_pending(self, session_id: str, job_id: str, pending_changes: list[dict]) -> None:
        changes = [{"change_id": c["change_id"], "approved": True} for c in pending_changes]
        response = self._request(
            "POST",
            f"/v1/chat/{session_id}/approve",
            json={"job_id": job_id, "approved": True, "changes": changes},
        )
        self._raise_for_error(response, f"POST /v1/chat/{session_id}/approve")

    def _continue_job(self, session_id: str, job_id: str, keep_going: bool) -> None:
        response = self._request(
            "POST", f"/v1/chat/{session_id}/continue", json={"job_id": job_id, "continue": keep_going}
        )
        self._raise_for_error(response, f"POST /v1/chat/{session_id}/continue")

    @staticmethod
    def _chat_result_from_payload(payload: dict) -> ChatResult:
        changes = payload.get("document_changes") or {}
        usage = payload.get("usage") or {}
        return ChatResult(
            response_text=payload.get("response", ""),
            updated_html=changes.get("updated_html"),
            changes_summary=changes.get("changes_summary"),
            monthly_used=usage.get("monthly_used"),
            monthly_remaining=usage.get("monthly_remaining"),
            was_billable=usage.get("was_billable"),
        )

    # ------------------------------------------------------------------
    # Export — POST /v1/documents/export. Small documents, so a plain
    # buffered read is the right complexity level (see module docstring).
    # ------------------------------------------------------------------
    def export_bytes(
        self, session_id: str, export_format: str, options: dict | None = None
    ) -> bytes:
        body: dict = {"session_id": session_id, "format": export_format}
        if options:
            body["options"] = options
        response = self._request("POST", "/v1/documents/export", json=body)
        self._raise_for_error(response, "POST /v1/documents/export")
        return response.content
