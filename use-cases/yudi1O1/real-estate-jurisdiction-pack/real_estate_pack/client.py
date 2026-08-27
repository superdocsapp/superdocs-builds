"""Minimal SuperDocs REST client: the four-call contract (upload, chat, approve,
export) plus the async/jobs plumbing HITL needs, and nothing else.

CARRIED OVER, DELIBERATELY. This module is reused essentially unchanged from the
sibling `supplier-quality-drafter` build in this same folder, where it was
hardened against live API behaviour over repeated real runs. Reusing it here is
the honest choice: the retry curve, the `Retry-After` handling and the
status-to-fix error table were all earned from live failures, and rewriting them
for a second project would mean re-earning them. The error guide below is
verbatim from that build; everything it says about /approve and /v1/users/* was
observed there, not guessed at here.

Deliberately hand-rolled rather than pulled from an SDK dependency — this file
is the whole integration surface, easy to read end to end in one sitting.

Two behaviors here exist because a document-drafting run costs real money and
takes real minutes, so it must not die on a blip:

* **Retries with backoff** on transient failures (429 + 5xx + connection
  errors), honoring `Retry-After` when the server sends it. A rate-limited or
  briefly-unavailable API degrades into a slower run, not a failed one.
* **Errors that name the cause AND the fix.** `_explain` turns a bare status
  code into a sentence an engineer can act on, because "500" on its own tells
  nobody what to do next.

Both are injectable (`session=`, `sleep=`) so `tests/test_client.py` can drive
them deterministically with no network and no real waiting.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests

DEFAULT_BASE_URL = "https://api.superdocs.app"

#: Statuses worth retrying. 4xx other than 429 are the caller's fault and
#: retrying them just burns time and (for billable calls) money.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

#: Status -> (cause, fix). Anything not listed falls back to a generic pair.
_ERROR_GUIDE: dict[int, tuple[str, str]] = {
    400: (
        "SuperDocs rejected the request body.",
        "Check the JSON you sent against docs.superdocs.app; a missing required field is the usual cause.",
    ),
    401: (
        "SuperDocs did not accept the API key.",
        "Check SUPERDOCS_API_KEY is set to a current sk_ key (use.superdocs.app -> Settings -> API Keys). "
        "Note /v1/users/* is web-app-only and always 401s for sk_ keys — verify with GET /v1/sessions instead.",
    ),
    403: (
        "The API key is valid but not allowed to do this.",
        "Confirm the key owns the session/document you are addressing; keys are scoped per account.",
    ),
    404: (
        "SuperDocs has no such session, job, or document.",
        "Check the id you passed. A session only exists once something has been uploaded or chatted into it.",
    ),
    413: (
        "The document or request is larger than the endpoint accepts.",
        "For documents over 20 MB use the pre-signed upload flow (request_upload_url -> PUT -> pass upload_id) "
        "rather than sending bytes inline. See docs.superdocs.app/concepts/documents#large-documents.",
    ),
    415: (
        "That file type is not supported.",
        "Convert the template to one of DOCX/DOC/ODT/PDF/TXT/HTML/MD/RTF before uploading.",
    ),
    422: (
        "SuperDocs understood the request but a field failed validation.",
        "On /approve this is almost always a missing top-level 'approved' field — it is required even when "
        "every entry in 'changes' carries its own.",
    ),
    429: (
        "Rate limit or monthly operation limit reached.",
        "This client already retried with backoff. If it persists, check remaining operations in the 'usage' "
        "block of any chat response, or upgrade the tier at use.superdocs.app.",
    ),
    500: ("SuperDocs hit an internal error.", "Retry; if it repeats, report it with the request you sent — that is a SuperDocs-side bug."),
    502: ("SuperDocs was unreachable through its gateway.", "Transient; this client retries. If it persists the service may be down — check GET /health."),
    503: ("SuperDocs is temporarily unavailable.", "Transient; this client retries. Check GET /health if it persists."),
    504: (
        "The request timed out server-side.",
        "Large documents and deep model tiers legitimately take minutes. Prefer /v1/chat/async + polling "
        "(which this client already uses for drafting) over the synchronous endpoint.",
    ),
}


def _explain(status: Optional[int], detail: Any = None) -> str:
    cause, fix = _ERROR_GUIDE.get(
        status or 0,
        ("The SuperDocs request failed.", "Check docs.superdocs.app for this endpoint's contract."),
    )
    parts = [f"[{status}] {cause}" if status else cause, f"Fix: {fix}"]
    if detail:
        parts.append(f"Server said: {str(detail)[:400]}")
    return " ".join(parts)


class SuperDocsError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class JobFailed(SuperDocsError):
    pass


class JobTimedOut(SuperDocsError):
    pass


@dataclass
class PendingChange:
    change_id: str
    operation: str
    chunk_id: Optional[str]
    old_html: Optional[str]
    new_html: Optional[str]
    ai_explanation: str


@dataclass
class UsageReport:
    """What a run cost, straight from SuperDocs' own `usage` block — reported,
    never estimated. `calls` is counted locally (how many billable requests this
    client issued); the rest is whatever the server last told us."""
    calls: int = 0
    monthly_used: Optional[int] = None
    monthly_limit: Optional[int] = None
    monthly_remaining: Optional[int] = None
    subscription_tier: Optional[str] = None

    def absorb(self, payload: Any) -> None:
        """Pull the usage block out of a chat or job-result payload, wherever it sits."""
        if not isinstance(payload, dict):
            return
        usage = payload.get("usage")
        if usage is None and isinstance(payload.get("result"), dict):
            usage = payload["result"].get("usage")
        if not isinstance(usage, dict):
            return
        self.monthly_used = usage.get("monthly_used", self.monthly_used)
        self.monthly_limit = usage.get("monthly_limit", self.monthly_limit)
        self.monthly_remaining = usage.get("monthly_remaining", self.monthly_remaining)
        self.subscription_tier = usage.get("subscription_tier", self.subscription_tier)

    def summary(self) -> str:
        if self.monthly_used is None:
            return f"{self.calls} billable request(s) issued; SuperDocs returned no usage block."
        return (
            f"{self.calls} billable request(s) issued. "
            f"Account: {self.monthly_used}/{self.monthly_limit} operations used this month "
            f"({self.monthly_remaining} remaining, tier={self.subscription_tier})."
        )


class SuperDocsClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_base: float = 1.5,
        session: Optional[Any] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise SuperDocsError(
                "No SuperDocs API key. Fix: set SUPERDOCS_API_KEY in your environment "
                "(create one at use.superdocs.app -> Settings -> API Keys)."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep
        self._session = session or requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})
        self.usage = UsageReport()

    # ---- low-level ----

    def _delay_for(self, attempt: int, response: Any) -> float:
        """Exponential backoff with jitter, unless the server named a wait itself."""
        retry_after = None
        headers = getattr(response, "headers", None) or {}
        try:
            raw = headers.get("Retry-After")
            if raw is not None:
                retry_after = float(raw)
        except (TypeError, ValueError):
            retry_after = None
        if retry_after is not None:
            return max(0.0, retry_after)
        return (self.backoff_base ** attempt) + random.uniform(0, 0.25)

    def _send(self, method: str, path: str, **kwargs) -> Any:
        """One HTTP round trip, retried on transient failure. Returns the response."""
        url = f"{self.base_url}{path}"
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as e:
                # Connection reset / DNS blip / read timeout: retry the same as a 503.
                last_error = e
                if attempt >= self.max_retries:
                    raise SuperDocsError(
                        f"{method} {path} failed to reach SuperDocs after {attempt + 1} attempt(s): {e}. "
                        "Fix: check network connectivity and https://api.superdocs.app/health."
                    ) from e
                self._sleep(self._delay_for(attempt, None))
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                self._sleep(self._delay_for(attempt, response))
                continue
            return response

        raise SuperDocsError(f"{method} {path} exhausted retries: {last_error}")

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self._send(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            raise SuperDocsError(
                f"{method} {path} -> {_explain(response.status_code, payload)}",
                response.status_code,
                payload,
            )
        content_type = (response.headers or {}).get("content-type", "")
        if content_type.startswith("application/json"):
            data = response.json()
            self.usage.absorb(data)
            return data
        return {"_raw": response.content}

    # ---- health / auth ----

    def health(self) -> dict:
        resp = self._send("GET", "/health")
        if resp.status_code >= 400:
            raise SuperDocsError(_explain(resp.status_code, getattr(resp, "text", None)), resp.status_code)
        return resp.json()

    def verify_key(self) -> bool:
        """Cheapest valid key check. Deliberately GET /v1/sessions, not /v1/users/me —
        the latter is web-app-only and 401s even for a good sk_ key."""
        try:
            self._request("GET", "/v1/sessions")
            return True
        except SuperDocsError as e:
            if e.status_code == 401:
                return False
            raise

    # ---- documents ----

    def upload_document(self, file_path: str, session_id: str, open_mode: Optional[str] = None) -> dict:
        data = {"session_id": session_id}
        if open_mode:
            data["open_mode"] = open_mode
        # Streamed straight off disk — the file's bytes never sit in a Python string.
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            return self._request("POST", "/v1/documents/upload", files=files, data=data)

    def export_document(
        self,
        out_path: str,
        session_id: Optional[str] = None,
        html: Optional[str] = None,
        format: str = "docx",
        options: Optional[dict] = None,
    ) -> str:
        body: dict[str, Any] = {"format": format}
        if session_id:
            body["session_id"] = session_id
        if html:
            body["html"] = html
        if options:
            body["options"] = options
        resp = self._send("POST", "/v1/documents/export", json=body)
        if resp.status_code >= 400:
            raise SuperDocsError(
                f"export -> {_explain(resp.status_code, getattr(resp, 'text', None))}", resp.status_code
            )
        with open(out_path, "wb") as f:
            f.write(resp.content)
        return out_path

    # ---- templates ----

    def upload_template(self, file_path: str) -> dict:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            return self._request("POST", "/v1/templates/upload", files=files)

    def list_templates(self) -> dict:
        return self._request("GET", "/v1/templates")

    # ---- chat (sync + async) ----

    def chat(self, message: str, session_id: str, document_html: Optional[str] = None, **extra) -> dict:
        body = {"message": message, "session_id": session_id, **extra}
        if document_html is not None:
            body["document_html"] = document_html
        self.usage.calls += 1
        return self._request("POST", "/v1/chat", json=body)

    def chat_async(self, message: str, session_id: str, document_html: Optional[str] = None, **extra) -> dict:
        body = {"message": message, "session_id": session_id, **extra}
        if document_html is not None:
            body["document_html"] = document_html
        self.usage.calls += 1
        return self._request("POST", "/v1/chat/async", json=body)

    def get_job(self, job_id: str) -> dict:
        return self._request("GET", f"/v1/jobs/{job_id}")

    def cancel_job(self, job_id: str) -> dict:
        return self._request("POST", f"/v1/jobs/{job_id}/cancel")

    def approve(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        change_id: Optional[str] = None,
        changes: Optional[list[dict]] = None,
        feedback: Optional[str] = None,
    ) -> dict:
        # Top-level `approved` is required by the schema even in batch shapes —
        # omitting it is the classic 422 (see _ERROR_GUIDE[422]).
        body: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id:
            body["change_id"] = change_id
        if changes is not None:
            body["changes"] = changes
        if feedback:
            body["feedback"] = feedback
        return self._request("POST", f"/v1/chat/{session_id}/approve", json=body)

    def continue_job(self, session_id: str, job_id: str, do_continue: bool) -> dict:
        return self._request(
            "POST", f"/v1/chat/{session_id}/continue", json={"job_id": job_id, "continue": do_continue}
        )

    def poll_job(
        self,
        job_id: str,
        poll_interval: float = 3.0,
        max_wait: float = 900.0,
        on_poll=None,
    ) -> dict:
        """Poll a job until it lands on a status that needs the caller's attention:
        completed, failed, cancelled, or awaiting_approval. Raises on failure/timeout.

        A long silence here is normal, not a hang: large documents and deep model
        tiers legitimately take minutes with no visible progress."""
        waited = 0.0
        while True:
            job = self.get_job(job_id)
            status = job.get("status")
            if on_poll:
                on_poll(job)
            if status in ("completed", "awaiting_approval", "cancelled"):
                self.usage.absorb(job)
                return job
            if status == "failed":
                raise JobFailed(
                    f"Job {job_id} failed: {job.get('error')}. "
                    "Fix: read the error above; if it names no cause, retry the draft — "
                    "a failed turn is not billed for the edit it never made.",
                    payload=job,
                )
            if waited >= max_wait:
                raise JobTimedOut(
                    f"Job {job_id} did not finish within {max_wait}s (last status={status}). "
                    "Fix: large documents can take several minutes — raise max_wait, or split the "
                    "draft into smaller turns.",
                    payload=job,
                )
            self._sleep(poll_interval)
            waited += poll_interval
