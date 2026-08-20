"""Thin REST client for the SuperDocs API (api.superdocs.app).

Implements exactly the endpoints this project uses — see architecture.md §3 for the
full list and why each one is needed. Every method mirrors the documented request/
response shape from docs.superdocs.app (fetched 2026-08-19); nothing here is invented.

No endpoint call in this file has been exercised against the live API — there was no
API key available while building (see progress.md). It is built strictly to the
documented contract and covered by tests using fixtures derived from that
documentation (tests/unit/test_client_mocked.py).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import requests

from .config import Settings


class SuperDocsAPIError(RuntimeError):
    """Raised for any non-2xx response from the SuperDocs API."""

    def __init__(self, status_code: int, detail: str, retry_after: float | None = None):
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after
        super().__init__(f"SuperDocs API error {status_code}: {detail}")


class OperationBudgetExceeded(RuntimeError):
    """Raised when a run's cumulative billable operations would exceed the cap.

    This is the "stopping rule" the assignment's practical notes ask for: a bug that
    loops chat calls cannot silently burn a whole monthly quota.
    """


@dataclass
class UsageTracker:
    max_operations: int
    ops_used: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(self, usage: dict[str, Any] | None, context: str) -> None:
        charged = int((usage or {}).get("ops_charged", 0))
        self.calls.append({"context": context, "ops_charged": charged, "usage": usage})
        self.ops_used += charged

    def check_budget(self, about_to_call: str) -> None:
        if self.ops_used >= self.max_operations:
            raise OperationBudgetExceeded(
                f"Operation budget ({self.max_operations}) reached before calling "
                f"'{about_to_call}'. Used {self.ops_used} ops across {len(self.calls)} "
                "calls this run. Raise WINLOSS_MAX_OPERATIONS if this is expected, or "
                "investigate a possible retry loop."
            )


class SuperDocsClient:
    """Minimal, typed wrapper. One method per endpoint actually used by this project."""

    def __init__(self, settings: Settings, api_key: str, session: requests.Session | None = None):
        self._settings = settings
        self._api_key = api_key
        self._http = session or requests.Session()
        self.usage = UsageTracker(max_operations=settings.max_operations)

    # -- low-level request helper -------------------------------------------------

    def _headers(self, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        expect_binary: bool = False,
        max_retries: int = 3,
    ) -> Any:
        url = f"{self._settings.base_url}{path}"
        content_type = None if files else "application/json"
        attempt = 0
        while True:
            attempt += 1
            resp = self._http.request(
                method,
                url,
                headers=self._headers(content_type),
                json=json if not files else None,
                data=data,
                files=files,
                params=params,
                timeout=self._settings.request_timeout_seconds,
            )
            if resp.status_code < 400:
                return resp.content if expect_binary else resp.json()

            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            if resp.status_code == 429 and attempt < max_retries:
                time.sleep(retry_after or min(2**attempt, 30))
                continue

            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            raise SuperDocsAPIError(resp.status_code, str(detail), retry_after)

    # -- attachments ----------------------------------------------------------------

    def upload_attachment(self, session_id: str, file_path: str) -> dict[str, Any]:
        """POST /v1/attachments/upload -- returns {job_id, filename, status, message}."""
        with open(file_path, "rb") as fh:
            return self._request(
                "POST",
                "/v1/attachments/upload",
                files={"file": fh},
                data={"session_id": session_id},
            )

    def attachment_status(self, session_id: str) -> dict[str, Any]:
        """GET /v1/attachments/status/{session_id}"""
        return self._request("GET", f"/v1/attachments/status/{session_id}")

    def wait_for_attachment(
        self, session_id: str, job_id: str, poll_interval: float | None = None, timeout: float | None = None
    ) -> dict[str, Any]:
        """Poll GET /v1/jobs/{job_id} (attachment jobs share the job namespace)."""
        return self.wait_for_job(job_id, poll_interval=poll_interval, timeout=timeout, stop_statuses=("completed", "failed"))

    # -- chat -------------------------------------------------------------------

    def chat(self, session_id: str, message: str, **kwargs: Any) -> dict[str, Any]:
        """POST /v1/chat (synchronous). Records usage from the response."""
        self.usage.check_budget("chat")
        payload = {"session_id": session_id, "message": message, **kwargs}
        result = self._request("POST", "/v1/chat", json=payload)
        self.usage.record(result.get("usage"), context=f"chat:{session_id}")
        return result

    def chat_async(self, session_id: str, message: str, **kwargs: Any) -> dict[str, Any]:
        """POST /v1/chat/async -- returns {job_id, ...} immediately."""
        self.usage.check_budget("chat_async")
        payload = {"session_id": session_id, "message": message, **kwargs}
        return self._request("POST", "/v1/chat/async", json=payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        """GET /v1/jobs/{job_id}"""
        return self._request("GET", f"/v1/jobs/{job_id}")

    def wait_for_job(
        self,
        job_id: str,
        poll_interval: float | None = None,
        timeout: float | None = None,
        stop_statuses: Iterable[str] = ("completed", "failed", "cancelled", "awaiting_approval"),
    ) -> dict[str, Any]:
        interval = poll_interval if poll_interval is not None else self._settings.poll_interval_seconds
        deadline = time.monotonic() + (timeout if timeout is not None else self._settings.poll_timeout_seconds)
        while True:
            job = self.get_job(job_id)
            if job.get("status") in stop_statuses:
                if job.get("status") == "completed" and "usage" in job.get("result", {}):
                    self.usage.record(job["result"]["usage"], context=f"job:{job_id}")
                return job
            if time.monotonic() > deadline:
                raise TimeoutError(f"Job {job_id} did not reach a terminal state within {timeout}s")
            time.sleep(interval)

    def approve_change(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        change_id: str | None = None,
        changes: list[dict[str, Any]] | None = None,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """POST /v1/chat/{session_id}/approve

        `approved` is REQUIRED at the top level even for batch shapes (documented
        footgun — see architecture.md and the HITL guide's explicit warning).
        """
        payload: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id is not None:
            payload["change_id"] = change_id
        if changes is not None:
            payload["changes"] = changes
        if feedback is not None:
            payload["feedback"] = feedback
        return self._request("POST", f"/v1/chat/{session_id}/approve", json=payload)

    # -- sessions / multi-document ------------------------------------------------

    def sessions_init(self, session_id: str | None = None, document_ids: list[str] | None = None) -> dict[str, Any]:
        """POST /v1/sessions/init"""
        payload: dict[str, Any] = {}
        if session_id:
            payload["session_id"] = session_id
        if document_ids:
            payload["document_ids"] = document_ids
        return self._request("POST", "/v1/sessions/init", json=payload)

    # -- documents (Files) ----------------------------------------------------------

    def list_documents(self, limit: int | None = None, offset: int | None = None) -> dict[str, Any]:
        """GET /v1/documents"""
        params = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset
        return self._request("GET", "/v1/documents", params=params or None)

    def get_document(self, document_id: str, include_html: bool = False) -> dict[str, Any]:
        """GET /v1/documents/{document_id}"""
        params = {"include_html": "true"} if include_html else None
        return self._request("GET", f"/v1/documents/{document_id}", params=params)

    # -- export -----------------------------------------------------------------

    def export(
        self,
        *,
        html: str | None = None,
        session_id: str | None = None,
        format: str = "docx",
        options: dict[str, Any] | None = None,
    ) -> bytes:
        """POST /v1/documents/export -- returns raw file bytes (non-billable)."""
        if not (html or session_id):
            raise ValueError("export() requires either html or session_id")
        payload: dict[str, Any] = {"format": format}
        if html is not None:
            payload["html"] = html
        if session_id is not None:
            payload["session_id"] = session_id
        if options:
            payload["options"] = options
        return self._request("POST", "/v1/documents/export", json=payload, expect_binary=True)


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
