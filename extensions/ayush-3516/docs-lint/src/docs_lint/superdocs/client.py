"""HTTP client for the SuperDocs endpoints docs-lint uses.

Deliberately small. This wraps seven calls, not the fifty the API offers, because the four-call
contract (upload, chat, approve, export) plus attachment upload, attachment status and quota is
everything a linter needs.

Two design notes:

*Retries are bounded and typed.* Only `retryable` errors are retried, with exponential backoff and
jitter. A 401 fails immediately - retrying a bad key just delays the message the user needs.

*The key never leaves this module.* It is not logged, not put in `repr`, and not included in error
bodies. `redact` scrubs it from any string that is about to be surfaced.
"""

from __future__ import annotations

import base64
import os
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .errors import (
    SuperDocsAuthError,
    SuperDocsBadRequest,
    SuperDocsError,
    SuperDocsJobFailed,
    SuperDocsJobTimeout,
    SuperDocsRateLimited,
    SuperDocsSessionBusy,
    SuperDocsUnavailable,
)
from .models import (
    Attachment,
    AttachmentStatus,
    AttachmentUpload,
    DocumentUpload,
    Job,
    JobStatus,
    Usage,
)

DEFAULT_BASE_URL = "https://api.superdocs.app"

#: Formats SuperDocs accepts as an attachment or document upload.
UPLOADABLE_SUFFIXES = frozenset({".pdf", ".docx", ".txt", ".rtf", ".md", ".html", ".htm"})


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff with full jitter.

    Jitter is not decoration: without it, several documents failing at the same moment retry in
    lockstep and hit the service as a synchronised wave.
    """

    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 8.0
    jitter: bool = True
    #: Separate ceiling for a server-sent Retry-After. `max_delay` bounds how fast our own
    #: backoff grows; it must not silently shorten a wait the server explicitly asked for,
    #: because retrying early just earns another 429. This bounds the pathological case only.
    max_retry_after: float = 60.0

    def delay_for(self, attempt: int, *, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_retry_after)
        raw = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        return random.uniform(0, raw) if self.jitter else raw


@dataclass
class CallLog:
    """What the client did, so a run can report where its time and money went.

    Counts requests rather than billed operations - only the service knows the latter, which is why
    the run also samples `whoami` either side and reports the delta.
    """

    requests: int = 0
    retries: int = 0
    seconds: float = 0.0
    by_endpoint: dict[str, int] = field(default_factory=dict)

    def record(self, endpoint: str, elapsed: float) -> None:
        self.requests += 1
        self.seconds += elapsed
        self.by_endpoint[endpoint] = self.by_endpoint.get(endpoint, 0) + 1


class SuperDocsClient:
    """Thin, typed, retrying client. One instance per run."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = 60.0,
        retry: RetryPolicy | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        key = api_key if api_key is not None else os.environ.get("SUPERDOCS_API_KEY", "")
        if not key:
            raise SuperDocsAuthError(
                "No SuperDocs API key. Set SUPERDOCS_API_KEY, or point SUPERDOCS_BASE_URL at a "
                "local FakeSuperDocs to run without spending operations."
            )
        self._api_key = key
        self.base_url = (
            base_url or os.environ.get("SUPERDOCS_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.retry = retry or RetryPolicy()
        self.log = CallLog()
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "docs-lint/0.1 (+https://github.com/superdocsapp/superdocs-builds)",
            },
        )

    # -- lifecycle ------------------------------------------------------------------

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SuperDocsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"SuperDocsClient(base_url={self.base_url!r})"

    def redact(self, text: str) -> str:
        """Strip the API key from anything about to be printed, logged or committed."""
        return text.replace(self._api_key, "sk_***") if self._api_key else text

    # -- transport ------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        last: SuperDocsError | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            started = time.monotonic()
            try:
                response = self._http.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self.log.record(path, time.monotonic() - started)
                last = SuperDocsUnavailable(f"{type(exc).__name__} calling {path}")
            else:
                self.log.record(path, time.monotonic() - started)
                error = self._error_for(response, path)
                if error is None:
                    return _json_object(response)
                last = error
            if not last.retryable or attempt == self.retry.max_attempts:
                raise last
            self.log.retries += 1
            self._sleep(
                self.retry.delay_for(attempt, retry_after=getattr(last, "retry_after", None))
            )
        raise last  # pragma: no cover - loop always raises or returns

    def _error_for(self, response: httpx.Response, path: str) -> SuperDocsError | None:
        if response.is_success:
            return None
        body = self.redact(response.text[:2000])
        status = response.status_code
        if status in (401, 403):
            return SuperDocsAuthError(
                "SuperDocs rejected the API key", status_code=status, body=body
            )
        if status == 429:
            return SuperDocsRateLimited(
                "Rate limited by SuperDocs",
                status_code=status,
                body=body,
                retry_after=_retry_after_seconds(response),
            )
        if status >= 500:
            return SuperDocsUnavailable(f"SuperDocs error on {path}", status_code=status, body=body)
        if status == 409:
            # The documented exception to "4xx is never retried". A session holds one active job,
            # and a job parked at awaiting_approval keeps holding it, so this is a transient
            # conflict wearing a client-error code (BUGS.md #8).
            detail = _detail(response)
            if detail.get("error_code") == "session_busy":
                return SuperDocsSessionBusy(
                    detail.get("message") or "Session already has an active job",
                    status_code=status,
                    body=body,
                    active_jobs=detail.get("active_jobs"),
                )
        return SuperDocsBadRequest(f"SuperDocs rejected {path}", status_code=status, body=body)

    # -- attachments (the style guide) ----------------------------------------------

    def upload_reference(
        self, filename: str, content: bytes, *, session_id: str, return_html: bool = False
    ) -> AttachmentUpload:
        """Upload a reference file the AI can consult while editing.

        This is how the style guide gets in: uploaded once, then named in the lint instruction.
        The guide is data on the service, not code in this repository.

        Returns an `AttachmentUpload` carrying a **job id**, not an attachment id - the attachment
        id does not exist yet. Use `wait_for_attachment` to get it.
        """
        payload = self._request(
            "POST",
            "/v1/attachments/upload-base64",
            json={
                "filename": filename,
                "file_base64": base64.b64encode(content).decode("ascii"),
                "session_id": session_id,
                "return_html": return_html,
            },
        )
        return AttachmentUpload.from_payload(payload, session_id=session_id)

    def attachment_status(self, session_id: str) -> AttachmentStatus:
        """Processing state of every attachment in a session.

        Attachments are searchable only once processing completes. Instructing an edit that cites
        the style guide before then spends an operation on a lint that could not read the rules.
        """
        payload = self._request("GET", f"/v1/attachments/status/{session_id}")
        return AttachmentStatus.from_payload(payload, session_id=session_id)

    def wait_for_attachment(
        self,
        upload: AttachmentUpload,
        *,
        timeout: float = 120.0,
        poll_interval: float = 2.0,
    ) -> Attachment:
        """Block until an uploaded reference is ready, and return it with its real id."""
        deadline = time.monotonic() + timeout
        while True:
            status = self.attachment_status(upload.session_id)
            ready = status.find_ready(filename=upload.filename, job_id=upload.job_id)
            if ready is not None:
                return ready
            failure = status.failure_for(upload.job_id)
            if failure is not None:
                raise SuperDocsError(f"Style guide {upload.filename} failed to process: {failure}")
            if time.monotonic() >= deadline:
                raise SuperDocsJobTimeout(
                    f"Attachment {upload.filename} not ready after {timeout:.0f}s",
                    job_id=upload.job_id,
                )
            self._sleep(poll_interval)

    # -- documents ------------------------------------------------------------------

    def upload_document(
        self, filename: str, content: bytes, *, session_id: str, return_html: bool = True
    ) -> DocumentUpload:
        """Upload the document under lint as the active editable document.

        `return_html=True` by default because the parsed HTML carries the `data-chunk-id`
        attributes, and that manifest is what every proposed change is validated against.
        """
        payload = self._request(
            "POST",
            "/v1/documents/upload-base64",
            json={
                "filename": filename,
                "file_base64": base64.b64encode(content).decode("ascii"),
                "session_id": session_id,
                "return_html": return_html,
            },
        )
        return DocumentUpload.from_payload(payload, session_id=session_id)

    def export(
        self,
        *,
        session_id: str,
        fmt: str = "markdown",
        html: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        """Export the current document. Exports do not cost operations."""
        body: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if html is not None:
            body["html"] = html
        if options:
            body["options"] = options
        payload = self._request("POST", "/v1/documents/export", json=body)

        # Export returns the file itself, not JSON, despite being documented as a JSON object
        # (BUGS.md #7). `_request` puts a non-JSON body under `raw_text`. Both are handled, so
        # this keeps working if the documented shape ever arrives.
        raw = payload.get("raw_text")
        if isinstance(raw, str):
            return raw
        for key in ("content", "text", "markdown", "data", "html"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        url = payload.get("download_url") or payload.get("url")
        if isinstance(url, str):
            return self._http.get(url).text
        raise SuperDocsError(f"Export returned no usable content (keys: {sorted(payload)})")

    # -- chat, the gate, and jobs ---------------------------------------------------

    def start_async_chat(
        self,
        *,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
        thinking_depth: str | None = None,
        window_id: str | None = None,
        document_id: str | None = None,
    ) -> str:
        """Start an async edit and return its job id.

        `approval_mode="ask_every_time"` is the default here on purpose. It is what makes the job
        stop at `awaiting_approval` and hand its proposals back for a human decision instead of
        writing them into the document. A linter that silently rewrites prose is the thing this
        project exists not to be.

        `window_id` lets the service tell concurrent writers apart, so two runs over the same
        repository do not get mistaken for one.
        """
        body: dict[str, Any] = {
            "session_id": session_id,
            "message": message,
            "approval_mode": approval_mode,
        }
        for key, value in (
            ("document_html", document_html),
            ("model_tier", model_tier),
            ("thinking_depth", thinking_depth),
            ("window_id", window_id),
            ("document_id", document_id),
        ):
            if value is not None:
                body[key] = value
        payload = self._request("POST", "/v1/chat/async", json=body)
        job_id = payload.get("job_id") or payload.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise SuperDocsError(f"Async chat returned no job_id (keys: {sorted(payload)})")
        return job_id

    def get_job(self, job_id: str) -> Job:
        payload = self._request("GET", f"/v1/jobs/{job_id}")
        return Job.from_payload({"job_id": job_id, **payload})

    def list_jobs(self, *, session_id: str | None = None) -> list[Job]:
        """Jobs for a session, most recent first.

        This is how a resumed run rediscovers work it already paid for: a job left at
        `awaiting_approval` by a killed process is still there, still holding its proposals.
        """
        params = {"session_id": session_id} if session_id else None
        payload = self._request("GET", "/v1/jobs", params=params)
        items = payload.get("data")
        if not isinstance(items, list):
            items = payload.get("jobs")
        if not isinstance(items, list):
            # The live endpoint returns a bare JSON array, which `_json_object` wraps as `data`.
            items = []
        return [Job.from_payload(item) for item in items if isinstance(item, dict)]

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel a pending or in-progress job, freeing its session.

        Needed because an abandoned approval blocks its session indefinitely (BUGS.md #8).
        """
        return self._request("POST", f"/v1/jobs/{job_id}/cancel")

    def poll_job(
        self,
        job_id: str,
        *,
        timeout: float = 600.0,
        poll_interval: float = 2.0,
        on_poll: Callable[[Job], None] | None = None,
    ) -> Job:
        """Poll until the job is terminal or needs us, then return it.

        Returns rather than raises at `awaiting_approval`: a job waiting for a human is a normal,
        successful outcome for this project, not an error.

        A timeout raises `SuperDocsJobTimeout` carrying the job id. The job may still be running
        server-side, so the caller records the id and resumes rather than paying for the edit twice.
        """
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id)
            if on_poll is not None:
                on_poll(job)
            if job.status is JobStatus.FAILED:
                raise SuperDocsJobFailed(
                    job.error or "SuperDocs job failed without an error message", job_id=job_id
                )
            if job.status.is_terminal or job.status.needs_caller:
                return job
            if time.monotonic() >= deadline:
                raise SuperDocsJobTimeout(
                    f"Job {job_id} still {job.status.value} after {timeout:.0f}s", job_id=job_id
                )
            self._sleep(poll_interval)

    def approve(
        self,
        *,
        session_id: str,
        job_id: str,
        decisions: Iterable[tuple[str, bool]],
        default_approved: bool = False,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """Submit per-change approve/reject decisions in one review.

        `decisions` is an iterable of `(change_id, approved)`. Rejecting one change leaves the rest
        untouched - that is the API's own batch semantics, not something reconstructed here.

        The top-level `approved` field is required by the API even for per-item batches, where it
        acts as the default for any change that does not carry its own. It defaults to `False`
        here: if a change somehow goes unlisted, the safe outcome is that it does not land.
        """
        changes = [
            {"change_id": change_id, "approved": bool(approved)}
            for change_id, approved in decisions
        ]
        if not changes:
            raise ValueError("approve() needs at least one decision")
        body: dict[str, Any] = {
            "job_id": job_id,
            "approved": default_approved,
            "changes": changes,
        }
        if feedback:
            body["feedback"] = feedback
        return self._request("POST", f"/v1/chat/{session_id}/approve", json=body)

    def continue_chat(
        self, *, session_id: str, job_id: str, proceed: bool = True
    ) -> dict[str, Any]:
        """Answer a large-edit continue prompt so the job can move on."""
        return self._request(
            "POST",
            f"/v1/chat/{session_id}/continue",
            json={"job_id": job_id, "continue": proceed},
        )

    # -- quota ----------------------------------------------------------------------

    def usage(self) -> Usage:
        """Account tier and monthly operation counters. Sampled either side of a run."""
        return Usage.from_payload(self._request("GET", "/v1/agents/whoami"))


def _json_object(response: httpx.Response) -> dict[str, Any]:
    """Parse a response body into a dict, tolerating an empty or non-object body."""
    if not response.content:
        return {}
    try:
        parsed = response.json()
    except ValueError:
        return {"raw_text": response.text}
    if isinstance(parsed, dict):
        return parsed
    return {"data": parsed}


def _detail(response: httpx.Response) -> dict[str, Any]:
    """Pull the structured error body out of a failed response.

    SuperDocs nests machine-readable errors under `detail` with an `error_code` and a
    `suggested_action`, which is more than most APIs offer and worth reading properly.
    """
    try:
        parsed = response.json()
    except ValueError:
        return {}
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    return detail if isinstance(detail, dict) else {}


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None
