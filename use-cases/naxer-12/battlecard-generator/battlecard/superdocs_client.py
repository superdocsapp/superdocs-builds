"""Thin client for the four SuperDocs REST calls this tool needs.

Every request/response shape here was verified against the real API (not
guessed from docs) while building a different SuperDocs build earlier in
this project: upload-base64 needs a client-generated session_id or it
never persists; chat/async's job result is nested under result.document_changes,
not top-level; approve requires job_id, not just approved; a job can go
straight from pending to completed with no awaiting_approval step; and
Content-Disposition can carry both filename="..." and filename*=UTF-8''...
on the same line, so only the quoted form should be parsed.
"""

from __future__ import annotations

import base64
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import requests

DEFAULT_BASE_URL = "https://api.superdocs.app"


class SuperDocsError(Exception):
    """Raised on any non-2xx response, with the real status/body attached."""

    def __init__(self, message: str, status_code: int, body: str):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class UploadResult:
    session_id: str
    filename: str
    persisted: bool
    chunks_count: Optional[int] = None
    version_id: Optional[str] = None


@dataclass
class ChatJobResult:
    job_id: str
    session_id: str
    status: str


@dataclass
class JobStatusResult:
    status: str
    updated_html: Optional[str]
    raw: dict


@dataclass
class ExportResult:
    file_bytes: bytes
    filename: str
    content_type: str


class SuperDocsClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, session: Optional[requests.Session] = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _raise_for_status(self, resp: requests.Response) -> None:
        if not (200 <= resp.status_code < 300):
            raise SuperDocsError(
                f"{resp.request.method} {resp.request.url} failed with {resp.status_code}",
                resp.status_code,
                resp.text,
            )

    def upload_document(self, file_bytes: bytes, filename: str, session_id: Optional[str] = None) -> UploadResult:
        """Uploads a file and persists it under a session. session_id is
        generated here if not supplied -- the real API does NOT auto-generate
        one, and a call without it never persists (verified live)."""
        sid = session_id or str(uuid.uuid4())
        resp = self._session.post(
            f"{self.base_url}/v1/documents/upload-base64",
            headers=self._headers(),
            json={
                "filename": filename,
                "file_base64": base64.b64encode(file_bytes).decode("ascii"),
                "session_id": sid,
                "return_html": True,
            },
        )
        self._raise_for_status(resp)
        data = resp.json()
        return UploadResult(
            session_id=data.get("session_id", sid),
            filename=data.get("filename", filename),
            persisted=data.get("persisted", False),
            chunks_count=data.get("chunks_count"),
            version_id=data.get("version_id"),
        )

    def start_edit(self, session_id: str, instruction: str) -> ChatJobResult:
        resp = self._session.post(
            f"{self.base_url}/v1/chat/async",
            headers=self._headers(),
            json={"message": instruction, "session_id": session_id},
        )
        self._raise_for_status(resp)
        data = resp.json()
        return ChatJobResult(job_id=data["job_id"], session_id=data["session_id"], status=data["status"])

    def get_job_status(self, job_id: str) -> JobStatusResult:
        resp = self._session.get(f"{self.base_url}/v1/jobs/{job_id}", headers=self._headers())
        self._raise_for_status(resp)
        data = resp.json()
        result = data.get("result") or {}
        document_changes = result.get("document_changes") or {}
        return JobStatusResult(
            status=data["status"],
            updated_html=document_changes.get("updated_html"),
            raw=data,
        )

    def wait_for_completion(self, job_id: str, timeout_s: float = 120.0, poll_interval_s: float = 2.0) -> JobStatusResult:
        deadline = time.monotonic() + timeout_s
        terminal = {"awaiting_approval", "completed", "failed", "cancelled"}
        while True:
            status = self.get_job_status(job_id)
            if status.status in terminal:
                return status
            if time.monotonic() > deadline:
                raise TimeoutError(f"job {job_id} did not finish within {timeout_s}s (last status: {status.status})")
            time.sleep(poll_interval_s)

    def approve(self, session_id: str, job_id: str, approved: bool) -> None:
        """No-op if the job already auto-completed -- calling approve() on an
        already-completed job returns a real 400 (verified live), so callers
        should check status before calling this, not call it unconditionally."""
        resp = self._session.post(
            f"{self.base_url}/v1/chat/{session_id}/approve",
            headers=self._headers(),
            json={"job_id": job_id, "approved": approved},
        )
        self._raise_for_status(resp)

    def export(self, session_id: str, format: str = "docx") -> ExportResult:
        resp = self._session.post(
            f"{self.base_url}/v1/documents/export",
            headers=self._headers(),
            json={"session_id": session_id, "format": format},
        )
        self._raise_for_status(resp)

        filename = f"exported_document.{format}"
        disposition = resp.headers.get("content-disposition", "")
        match = re.search(r'filename="([^"]+)"', disposition)
        if match:
            filename = match.group(1)

        return ExportResult(
            file_bytes=resp.content,
            filename=filename,
            content_type=resp.headers.get("content-type", "application/octet-stream"),
        )
