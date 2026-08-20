"""A thin SuperDocs REST client, covering the four calls the brief calls the minimum
contract: upload a document, send an edit instruction, approve the proposed changes,
export the finished file. Plus attachment upload, which is what makes the style guide
a knowledge base rather than hardcoded rules.

Two behaviours here exist because of something observed, not something documented:

1. `chat` can report a timeout for a job that succeeded. Observed 2026-08-11
   (bug-log entry 1): the call returned "The operation timed out." while the job
   showed `completed` and the edit had landed. A caller that reads timeout as failure
   and retries pays twice for the same edit. So a timeout is never final here: it
   resolves against the job list, and the job decides.

2. Long operations look identical to hangs. The brief is explicit that "the correct
   read is still processing, not a crash", so waits are bounded by a deadline the
   caller sets, and report progress rather than blocking silently.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

DEFAULT_BASE_URL = "https://api.superdocs.app"

# Our threshold, not the API's. Inline base64 is reliable well above this; 100 KB is
# where we switch to pre-signed to keep request bodies small. Stated plainly because
# an invented "documented limit" is the kind of claim a reviewer checks.
INLINE_UPLOAD_LIMIT = 100 * 1024

# The pre-signed URL is signed over the content type declared when the ticket was
# issued, so the PUT must send the same one. Omitting it returns 400
# MalformedSecurityHeader from the storage backend, not from SuperDocs — which is a
# confusing place to land. Verified 2026-08-19.
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".tex": "application/x-tex",
    ".zip": "application/zip",
}


def content_type_for(path: "Path") -> str:
    return CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")

# Statuses that end a wait. `awaiting_approval` is a resting state, not a failure:
# the job is holding the proposed changes until someone approves or denies them.
TERMINAL = {"completed", "succeeded", "done"}
AWAITING = {"awaiting_approval", "awaiting_review", "needs_approval"}
FAILED = {"failed", "error", "cancelled", "canceled"}


class SuperDocsError(RuntimeError):
    """An API call failed in a way the caller must not paper over."""

    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class TimedOut(SuperDocsError):
    """Transport-level timeout. Says nothing about whether the work succeeded."""


@dataclass
class Usage:
    """What a run cost. Recorded per stage, never estimated."""

    operations: int = 0
    calls: int = 0
    seconds: float = 0.0
    by_stage: dict[str, int] = field(default_factory=dict)

    def record(self, stage: str, operations: int = 1) -> None:
        self.operations += operations
        self.by_stage[stage] = self.by_stage.get(stage, 0) + operations


class SuperDocsClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        on_event: Callable[[str, str], None] | None = None,
    ) -> None:
        if not api_key:
            raise SuperDocsError("no API key: set SUPERDOCS_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.usage = Usage()
        self._on_event = on_event or (lambda stage, msg: None)
        self._session = requests.Session()
        self._session.headers.update(
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        )

    def _call(self, method: str, path: str, stage: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        started = time.monotonic()
        self.usage.calls += 1
        try:
            r = self._session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.Timeout as exc:
            raise TimedOut(f"{method} {path} timed out after {self.timeout}s") from exc
        finally:
            self.usage.seconds += time.monotonic() - started

        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = r.text[:400]
            raise SuperDocsError(
                f"{method} {path} -> {r.status_code}: {body}", r.status_code, body
            )
        return r.json() if r.content else {}

    def init_session(self, session_id: str) -> dict:
        return self._call("POST", "/v1/sessions/init", "session",
                          json={"session_id": session_id})

    def upload_document(self, path: str | Path, session_id: str) -> dict:
        """Upload a document. Uploads and exports do not cost operations."""
        p = Path(path)
        data = p.read_bytes()
        if len(data) > INLINE_UPLOAD_LIMIT:
            return self._upload_presigned(p, data, session_id)
        self._on_event("upload", f"{p.name} ({len(data)} bytes, inline)")
        return self._call(
            "POST", "/v1/documents/upload-base64", "upload",
            json={
                "filename": p.name,
                "file_base64": base64.b64encode(data).decode(),
                "session_id": session_id,
                "return_html": True,
            },
        )

    def _upload_presigned(self, p: Path, data: bytes, session_id: str) -> dict:
        """Bodies over 100 KB go via a pre-signed URL, per the documented threshold."""
        self._on_event("upload", f"{p.name} ({len(data)} bytes, pre-signed)")
        declared = content_type_for(p)
        ticket = self._call("POST", "/v1/uploads", "upload",
                            json={"filename": p.name,
                                  "size_bytes": len(data),
                                  "content_type": declared})
        put_url = ticket.get("upload_url") or ticket.get("url")
        upload_id = ticket.get("upload_id") or ticket.get("id")
        if not put_url or not upload_id:
            raise SuperDocsError(f"upload ticket missing url/id: {sorted(ticket)}")
        # The Content-Type must match the ticket, or the signed URL rejects it.
        put = requests.put(put_url, data=data, timeout=self.timeout,
                           headers={"Content-Type": declared})
        if put.status_code >= 400:
            raise SuperDocsError(f"pre-signed PUT -> {put.status_code}", put.status_code)
        return self._call("POST", f"/v1/uploads/{upload_id}/process", "upload",
                          json={"session_id": session_id, "filename": p.name,
                                "return_html": True})

    def upload_attachment(self, path: str | Path, session_id: str) -> dict:
        """The style guide. This is what makes the rules swappable with no code edit."""
        p = Path(path)
        self._on_event("attach", p.name)
        return self._call(
            "POST", "/v1/attachments/upload-base64", "attach",
            json={
                "filename": p.name,
                "file_base64": base64.b64encode(p.read_bytes()).decode(),
                "session_id": session_id,
            },
        )

    def chat_async(self, session_id: str, message: str, **options) -> dict:
        """Start an edit and return the job. This is the surface that supports
        human approval: the job parks at `awaiting_approval` carrying the proposed
        changes in `metadata.pending_changes`, and nothing is applied until they are
        approved. The synchronous `chat` route applies its edits itself, which is the
        wrong shape for a linter whose whole point is a gate before anything commits.
        """
        payload: dict[str, Any] = {
            "session_id": session_id,
            "message": message,
            "approval_mode": options.pop("approval_mode", "ask_every_time"),
            "response_mode": options.pop("response_mode", "compact"),
        }
        payload.update({k: v for k, v in options.items() if v is not None})
        self.usage.record("chat")
        started = self._call("POST", "/v1/chat/async", "chat", json=payload)
        job_id = started.get("job_id") or started.get("id")
        if not job_id:
            raise SuperDocsError(f"chat_async returned no job id: {sorted(started)}")
        return self.wait_for_job(session_id, job_id)

    def attachment_ready(self, session_id: str, deadline_seconds: float = 120.0,
                         interval: float = 2.0) -> dict:
        """Attachments are processed asynchronously and are only searchable once
        ready. Without this wait the model lints against a guide that is not there
        yet and reports a clean document - a silent falsification of the one claim
        this build rests on.
        """
        started = time.monotonic()
        while True:
            status = self._call("GET", f"/v1/attachments/status/{session_id}", "attach")
            # Real shape, captured 2026-08-19 (tests/fixtures/attachment_status.json):
            # {session_id, ready_attachments:[...], processing_jobs:[...],
            #  total_ready:int, total_processing:int}
            ready = status.get("total_ready", 0)
            processing = status.get("total_processing", 0)
            jobs = status.get("processing_jobs") or []
            failed = [j for j in jobs if str(j.get("status", "")).lower() in FAILED]
            self._on_event("attach", f"{ready} ready, {processing} processing")
            if failed:
                raise SuperDocsError(f"style guide failed to process: {failed[0]}")
            if ready and not processing:
                return status
            if time.monotonic() - started > deadline_seconds:
                raise SuperDocsError(
                    f"style guide still processing after {deadline_seconds}s "
                    f"- refusing to lint against a guide that may not be loaded")
            time.sleep(interval)

    def chat(self, session_id: str, message: str, **options) -> dict:
        """Send an edit instruction. One operation, or one per 25 sections changed.

        A transport timeout is not a failure: it resolves against the job list,
        because the edit may well have landed (bug-log entry 1).
        """
        payload: dict[str, Any] = {
            "session_id": session_id,
            "message": message,
            "approval_mode": options.pop("approval_mode", "ask_every_time"),
            "response_mode": options.pop("response_mode", "compact"),
        }
        payload.update({k: v for k, v in options.items() if v is not None})
        self.usage.record("chat")
        try:
            return self._call("POST", "/v1/chat", "chat", json=payload)
        except TimedOut as exc:
            self._on_event("chat", f"{exc} - resolving against the job list")
            job = self.latest_job(session_id)
            if job is None:
                raise
            job_id = job.get("job_id") or job.get("id")
            return {"recovered_from_timeout": True,
                    "job": self.wait_for_job(session_id, job_id)}

    def approve(self, session_id: str, job_id: str, approved: bool,
                change_id: str | None = None, feedback: str | None = None) -> dict:
        """Approve or deny. Denying one item must leave the others untouched."""
        body: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id is not None:
            body["change_id"] = change_id
        if feedback is not None:
            body["feedback"] = feedback
        return self._call("POST", f"/v1/chat/{session_id}/approve", "approve", json=body)

    def export(self, session_id: str, fmt: str = "docx",
               filename: str | None = None) -> dict:
        """Export. Free - the brief says exports do not cost operations."""
        body: dict[str, Any] = {"session_id": session_id, "format": fmt}
        if filename:
            body["filename"] = filename
        return self._call("POST", "/v1/documents/export", "export", json=body)

    def export_to_file(self, session_id: str, destination: str | Path,
                       fmt: str = "docx") -> Path:
        """Export and write the bytes to disk.

        The two surfaces differ here, confirmed live 2026-08-19: REST
        `POST /v1/documents/export` streams the file itself (a .docx arrives as
        `PK..` bytes, not JSON), while the same operation over MCP returns a JSON
        envelope carrying a short-lived signed `download_url`. Both are handled,
        because returning an envelope and calling that "exported" would leave the
        last of the four contract calls not actually producing a file.
        """
        out = Path(destination)
        body: dict[str, Any] = {"session_id": session_id, "format": fmt}
        response = self._session.post(f"{self.base_url}/v1/documents/export",
                                      json=body, timeout=self.timeout)
        if response.status_code >= 400:
            raise SuperDocsError(f"export -> {response.status_code}: "
                                 f"{response.text[:300]}", response.status_code)

        if "application/json" in response.headers.get("content-type", ""):
            envelope = response.json()
            url = envelope.get("download_url") or envelope.get("url")
            if url:
                got = requests.get(url, timeout=self.timeout)
                if got.status_code >= 400:
                    raise SuperDocsError(f"download {got.status_code} from signed URL",
                                         got.status_code)
                out.write_bytes(got.content)
            else:
                text = (envelope.get("content") or envelope.get("html")
                        or envelope.get("text"))
                if text is None:
                    raise SuperDocsError(
                        f"export returned neither a download_url nor content: "
                        f"{sorted(envelope)}")
                out.write_text(text, encoding="utf-8")
        else:
            out.write_bytes(response.content)

        self._on_event("export", f"{out} ({out.stat().st_size} bytes)")
        return out

    def jobs(self, session_id: str) -> list[dict]:
        got = self._call("GET", f"/v1/sessions/{session_id}/jobs", "poll")
        if isinstance(got, list):
            return got
        return got.get("jobs", [])

    def latest_job(self, session_id: str) -> dict | None:
        found = self.jobs(session_id)
        return found[0] if found else None

    def wait_for_job(self, session_id: str, job_id: str,
                     deadline_seconds: float = 1800.0,
                     interval: float = 5.0,
                     require_completed: bool = False) -> dict:
        """Wait for a job, reporting progress. Slow means processing, not crashed."""
        started = time.monotonic()
        while True:
            job = self._call("GET", f"/v1/jobs/{job_id}", "poll")
            status = str(job.get("status", "")).lower()
            self._on_event("poll", f"{job_id} {status} {job.get('progress', '')}")
            if status in TERMINAL:
                return job
            if status in AWAITING and not require_completed:
                return job
            if status in FAILED:
                raise SuperDocsError(f"job {job_id} ended {status}", body=job)
            if time.monotonic() - started > deadline_seconds:
                raise SuperDocsError(
                    f"job {job_id} still {status} after {deadline_seconds}s "
                    f"- still processing, not abandoned; poll it later", body=job)
            time.sleep(interval)
