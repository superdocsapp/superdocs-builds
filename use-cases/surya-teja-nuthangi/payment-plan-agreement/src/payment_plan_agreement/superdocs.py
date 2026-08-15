from __future__ import annotations

import io
import json
import os
import socket
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from .models import ProposedChange, ReviewDecision


class SuperDocsError(RuntimeError): pass
class SuperDocsUnauthorized(SuperDocsError): pass
class SuperDocsRateLimited(SuperDocsError): pass
class SuperDocsTimeout(SuperDocsError): pass
class SuperDocsMalformedProposal(SuperDocsError): pass
class SuperDocsJobFailed(SuperDocsError): pass
class SuperDocsApprovalRejected(SuperDocsError): pass
class SuperDocsExportFailed(SuperDocsError): pass


class EditJob(BaseModel):
    job_id: str
    session_id: str
    status: str
    proposals: list[ProposedChange] = Field(default_factory=list)
    document_html: str | None = None
    progress: int = 0
    error: str | None = None


class ExportedDocument(BaseModel):
    filename: str
    mime_type: str
    content: bytes
    model_config = {"arbitrary_types_allowed": True}


class SuperDocsClient(Protocol):
    def start_edit(self, session_id: str, document_html: str, message: str) -> EditJob: ...
    def get_job(self, job_id: str) -> EditJob: ...
    def approve(self, session_id: str, job_id: str, decisions: list[ReviewDecision]) -> EditJob: ...
    def export(self, *, html: str, filename: str) -> ExportedDocument: ...


def parse_proposal(value: object) -> ProposedChange:
    parsed = value
    for _ in range(2):
        if isinstance(parsed, str):
            try: parsed = json.loads(parsed)
            except json.JSONDecodeError as exc: raise SuperDocsMalformedProposal("proposed change is invalid JSON") from exc
    if not isinstance(parsed, dict): raise SuperDocsMalformedProposal("proposed change is not an object")
    try: return ProposedChange.model_validate(parsed)
    except Exception as exc: raise SuperDocsMalformedProposal("proposed change does not match the documented schema") from exc


class HttpSuperDocsClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 30) -> None:
        self._api_key = api_key or os.environ.get("SUPERDOCS_API_KEY")
        if not self._api_key: raise SuperDocsUnauthorized("SUPERDOCS_API_KEY is required server-side; no external request was made")
        self._base = (base_url or os.environ.get("SUPERDOCS_BASE_URL") or "https://api.superdocs.app").rstrip("/")
        self._timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None, binary: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self._base + path, data=data, method=method, headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                return raw if binary else (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            if exc.code == 401: raise SuperDocsUnauthorized("SuperDocs authentication failed; work is preserved; replace the server-side key") from exc
            if exc.code == 429: raise SuperDocsRateLimited("SuperDocs rate limited the request; work is preserved; retry later") from exc
            raise SuperDocsError(f"SuperDocs request failed with HTTP {exc.code}; work is preserved") from exc
        except (TimeoutError, socket.timeout) as exc: raise SuperDocsTimeout("SuperDocs timed out; work is preserved; polling/retry is safe for this read") from exc
        except urllib.error.URLError as exc: raise SuperDocsError("SuperDocs could not be reached; work is preserved; check the network and retry") from exc

    def start_edit(self, session_id: str, document_html: str, message: str) -> EditJob:
        result = self._request("POST", "/v1/chat/async", {"session_id": session_id, "document_html": document_html, "message": message, "approval_mode": "ask_every_time"})
        return EditJob(job_id=result["job_id"], session_id=result.get("session_id", session_id), status=result.get("status", "pending"))

    def get_job(self, job_id: str) -> EditJob:
        result = self._request("GET", f"/v1/jobs/{job_id}")
        if result.get("status") == "failed": raise SuperDocsJobFailed("SuperDocs edit failed; seed and canonical plan are preserved; inspect the job error before retry")
        if result.get("status") == "cancelled": raise SuperDocsJobFailed("SuperDocs edit was cancelled; seed and canonical plan are preserved")
        metadata = result.get("metadata") or {}
        proposals = [parse_proposal(x) for x in metadata.get("pending_changes", [])]
        job_result = result.get("result") or {}
        document_changes = job_result.get("document_changes") or {}
        return EditJob(
            job_id=job_id,
            session_id=result.get("session_id", ""),
            status=result["status"],
            proposals=proposals,
            document_html=result.get("document_html") or document_changes.get("updated_html"),
            progress=result.get("progress", 0),
            error=result.get("error"),
        )

    def approve(self, session_id: str, job_id: str, decisions: list[ReviewDecision]) -> EditJob:
        result = self._request("POST", f"/v1/chat/{session_id}/approve", {"job_id": job_id, "approved": all(x.approved for x in decisions), "changes": [x.model_dump(exclude_none=True) for x in decisions]})
        return EditJob(job_id=job_id, session_id=session_id, status=result.get("status", "in_progress"), document_html=result.get("document_html"), progress=result.get("progress", 0))

    def export(self, *, html: str, filename: str) -> ExportedDocument:
        stem = filename[:-5] if filename.lower().endswith(".docx") else filename
        content = self._request("POST", "/v1/documents/export", {"html": html, "format": "docx", "options": {"filename": stem}}, binary=True)
        if not content.startswith(b"PK"): raise SuperDocsExportFailed("SuperDocs export did not return a valid DOCX ZIP; final HTML is preserved")
        return ExportedDocument(filename=filename, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", content=content)


@dataclass
class FakeSuperDocsClient:
    mode: str = "success"

    def __post_init__(self) -> None:
        self.jobs: dict[str, EditJob] = {}
        self.documents: dict[str, str] = {}

    def start_edit(self, session_id: str, document_html: str, message: str) -> EditJob:
        if self.mode == "api_failure": raise SuperDocsError("Fake external operation failed; seed is preserved; retry is safe")
        job_id = "job_" + uuid.uuid4().hex
        self.documents[session_id] = document_html
        new_text = "Contact the Creditor promptly" if self.mode != "protected_amount" else "Original balance: $9,999.00"
        proposal = ProposedChange(change_id="change_1", operation="edit", chunk_id="general" if self.mode != "protected_amount" else "amounts", old_html="", new_html=new_text, ai_explanation="Plain-language edit")
        job = EditJob(job_id=job_id, session_id=session_id, status="awaiting_approval", proposals=[proposal])
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> EditJob: return self.jobs[job_id]

    def approve(self, session_id: str, job_id: str, decisions: list[ReviewDecision]) -> EditJob:
        approved = {x.change_id for x in decisions if x.approved}
        job = self.jobs[job_id]
        if self.mode == "approval_failure": raise SuperDocsApprovalRejected("Fake approval failed; proposals and decisions are preserved")
        html = self.documents[session_id]
        if "change_1" in approved and self.mode == "protected_amount": html = html.replace("Original balance: $1,000.00", "Original balance: $9,999.00")
        completed = job.model_copy(update={"status": "completed", "document_html": html})
        self.jobs[job_id] = completed
        return completed

    def export(self, *, html: str, filename: str) -> ExportedDocument:
        if self.mode == "export_failure": raise SuperDocsExportFailed("Fake export failed; verified final HTML is preserved")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive: archive.writestr("[Content_Types].xml", "<Types/>"); archive.writestr("word/document.xml", html)
        return ExportedDocument(filename=filename, mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", content=output.getvalue())


def poll_job(client: SuperDocsClient, job_id: str, *, terminal_statuses: set[str], timeout_seconds: float = 180, interval_seconds: float = 2) -> EditJob:
    """Poll a durable async job without hammering the API."""
    deadline = time.monotonic() + timeout_seconds
    last: EditJob | None = None
    while time.monotonic() < deadline:
        last = client.get_job(job_id)
        if last.status in terminal_statuses:
            return last
        time.sleep(interval_seconds)
    progress = last.progress if last else 0
    raise SuperDocsTimeout(f"SuperDocs job did not reach {sorted(terminal_statuses)} before the timeout (last progress {progress}%); work and job id are preserved")
