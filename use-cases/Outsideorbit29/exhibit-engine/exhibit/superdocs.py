"""Thin client for the SuperDocs Universal Document AI API.

Implements exactly the four calls the task's minimum contract requires, plus
the job polling that makes an async chat usable:

    1. upload_base64   — POST /v1/documents/upload-base64
    2. chat_async      — POST /v1/chat/async        (approval_mode='ask_every_time')
    3. approve         — POST /v1/chat/{session_id}/approve
    4. export          — POST /v1/documents/export

``poll_job`` (GET /v1/jobs/{job_id}) turns the async job into a usable flow:
the caller waits for status to leave ``pending``/``in_progress``, reviews
``metadata.pending_changes`` when ``awaiting_approval``, then approves and waits
for ``completed``.

Kept dependency-light on purpose: ``httpx`` only. The base URL and key are taken
from constructor args so the same client can drive the real API or the local
mock server in tests.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_URL = "https://api.superdocs.app"
DEFAULT_TIMEOUT = 120.0

TERMINAL = {"completed", "failed", "cancelled"}


class SuperDocsError(RuntimeError):
    """Raised when SuperDocs returns an unexpected status or malformed payload."""


@dataclass
class UploadResult:
    session_id: str
    document_id: str | None = None
    chunks_count: int | None = None
    version_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExportResult:
    content: bytes
    content_type: str
    filename: str | None = None


@dataclass
class Job:
    """A slim view of a job, parsed from the JobResponse schema."""

    job_id: str
    session_id: str
    status: str
    progress: int
    pending_changes: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Job":
        metadata = payload.get("metadata") or {}
        return cls(
            job_id=payload.get("job_id", ""),
            session_id=payload.get("session_id", ""),
            status=payload.get("status", ""),
            progress=payload.get("progress", 0),
            pending_changes=metadata.get("pending_changes") or [],
            result=payload.get("result"),
            error=payload.get("error"),
            raw=payload,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL

    @property
    def is_done(self) -> bool:
        return self.status == "completed"


class SuperDocsClient:
    """Minimal, typed client for the SuperDocs API."""

    def __init__(self, base_url: str = BASE_URL, api_key: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    # -- 1. upload ----------------------------------------------------------------

    def upload_base64(self, filename: str, file_base64: str,
                      session_id: str | None = None, return_html: bool = False) -> UploadResult:
        # The real API only *persists* a document (making it editable via chat)
        # when the upload carries a session_id; without one it is a one-off
        # conversion that returns no session. Mint a session id client-side so the
        # four-call contract always has a durable document to edit.
        if session_id is None:
            session_id = _new_session_id()
        body = {"filename": filename, "file_base64": file_base64, "session_id": session_id}
        if return_html:
            body["return_html"] = True
        data = self._post("/v1/documents/upload-base64", json=body)
        return UploadResult(
            session_id=data.get("session_id") or session_id,
            document_id=data.get("document_id"),
            chunks_count=data.get("chunks_count"),
            version_id=data.get("version_id"),
            raw=data,
        )

    # -- 2. chat (async, approval-gated) ------------------------------------------

    def chat_async(self, message: str, session_id: str,
                   document_html: str | None = None,
                   approval_mode: str = "ask_every_time",
                   response_mode: str = "compact",
                   model_tier: str | None = None,
                   thinking_depth: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "response_mode": response_mode,
            "async_mode": True,
        }
        if document_html is not None:
            body["document_html"] = document_html
        if model_tier is not None:
            body["model_tier"] = model_tier
        if thinking_depth is not None:
            body["thinking_depth"] = thinking_depth
        return self._post("/v1/chat/async", json=body)

    # -- job polling ----------------------------------------------------------------

    def get_job(self, job_id: str) -> Job:
        data = self._get(f"/v1/jobs/{job_id}")
        return Job.from_payload(data)

    def poll_job(self, job_id: str, interval: float = 2.0,
                 timeout: float = 600.0) -> Job:
        """Poll until the job leaves pending/in_progress (or fails/times out)."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id)
            if job.status not in {"pending", "in_progress"} or job.is_terminal:
                return job
            if time.monotonic() >= deadline:
                raise TimeoutError(f"job {job_id} still {job.status!r} after {timeout}s")
            time.sleep(interval)

    # -- 3. approve -----------------------------------------------------------------

    def approve(self, session_id: str, job_id: str, *, approved: bool = True,
                change_id: str | None = None, feedback: str | None = None,
                changes: list[dict[str, Any]] | None = None) -> None:
        body: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id is not None:
            body["change_id"] = change_id
        if feedback is not None:
            body["feedback"] = feedback
        if changes is not None:
            body["changes"] = changes
        self._post(f"/v1/chat/{session_id}/approve", json=body)

    # -- 4. export -------------------------------------------------------------------

    def export(self, session_id: str, fmt: str = "pdf",
               options: dict[str, Any] | None = None,
               filename: str | None = None,
               html: str | None = None) -> ExportResult:
        body: dict[str, Any] = {"format": fmt}
        if session_id:
            body["session_id"] = session_id
        if html is not None:
            body["html"] = html
        if options is not None:
            body["options"] = options
        elif filename is not None:
            body["filename"] = filename
        resp = self._request("POST", "/v1/documents/export", json=body, raw=True)
        ctype = resp.headers.get("content-type", "application/octet-stream")
        fname = _filename_from_disposition(resp.headers.get("content-disposition"))
        return ExportResult(content=resp.content, content_type=ctype, filename=fname)

    # -- low-level --------------------------------------------------------------------

    def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        resp = self._request("POST", path, json=json)
        return _as_json(resp, path)

    def _get(self, path: str) -> dict[str, Any]:
        resp = self._request("GET", path)
        return _as_json(resp, path)

    def _request(self, method: str, path: str, *, json: dict[str, Any] | None = None,
                 raw: bool = False) -> httpx.Response:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.request(method, url, json=json, headers=self._headers)
        if resp.status_code >= 400:
            detail = resp.text[:300]
            raise SuperDocsError(f"{method} {path} -> {resp.status_code}: {detail}")
        return resp


def _as_json(resp: httpx.Response, path: str) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError as exc:  # pragma: no cover - defensive
        raise SuperDocsError(f"{path} returned non-JSON: {resp.text[:200]}") from exc
    if not isinstance(data, dict):
        raise SuperDocsError(f"{path} returned a non-object payload: {data!r}")
    return data


def _filename_from_disposition(disposition: str | None) -> str | None:
    if not disposition:
        return None
    for part in disposition.split(";"):
        part = part.strip()
        if part.lower().startswith("filename="):
            name = part[len("filename="):].strip('"')
            if name:
                return name
    return None


def encode_file(path: str) -> str:
    """Read a file and return its base64 payload for upload."""
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def _new_session_id() -> str:
    """Mint a session id that matches the API's ``^[a-zA-Z0-9_\\-.]+$`` pattern."""
    import uuid
    return f"sess-{uuid.uuid4().hex}"
