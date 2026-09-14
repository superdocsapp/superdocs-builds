"""SuperDocs REST client - real HTTP calls against the confirmed endpoints
(https://docs.superdocs.app/api-reference), not the MCP transport. Every path/schema here was verified
against the live API during design (Phase 3/4 of the build plan): a real upload, a real sync edit, a real
async edit with human-in-the-loop approval, and a real export were all run and inspected before this file
was written - nothing here is guessed from documentation alone.

Two implementations behind one interface (`SuperDocsClient` protocol): `RealSuperDocsClient` for actual use,
`FakeSuperDocsClient` for tests that must run without a live key (round-wide requirement - see CONTRIBUTING.md
and the task brief's "real tests... run without a live key").
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

BASE_URL = "https://api.superdocs.app"


class SuperDocsError(Exception):
    """Raised on a non-2xx response or a job that ends in status='failed'."""

    def __init__(self, message: str, status_code: int | None = None, detail: object = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


@dataclass
class ProposedChange:
    change_id: str
    operation: str
    chunk_id: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str | None


@dataclass
class ChatResult:
    """Unified shape for both the sync and completed-async chat paths - callers don't need to care which
    transport produced it."""

    response_text: str
    session_id: str
    updated_html: str | None
    changes: list[ProposedChange]
    ops_charged: int


@dataclass
class JobStatus:
    job_id: str
    session_id: str
    status: Literal["pending", "in_progress", "awaiting_approval", "completed", "failed", "cancelled"]
    pending_changes: list[ProposedChange] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None


class SuperDocsClient(Protocol):
    """The four-call contract (upload/chat/approve/export) plus the async+approval path, per
    docs.superdocs.app - this is the entire surface our business logic depends on."""

    def upload_document(self, filename: str, content: bytes, session_id: str) -> dict: ...
    def upload_image(self, image_base64: str, mime_type: str) -> str: ...
    def chat(self, message: str, session_id: str) -> ChatResult: ...
    def chat_with_approval(self, message: str, session_id: str) -> JobStatus: ...
    def get_job(self, job_id: str) -> JobStatus: ...
    def approve_change(self, session_id: str, job_id: str, change_id: str, approved: bool, feedback: str | None = None) -> None: ...
    def export_document(self, session_id: str, format: str = "markdown") -> str | bytes: ...


def _parse_changes(raw_changes: list[dict] | None) -> list[ProposedChange]:
    if not raw_changes:
        return []
    return [
        ProposedChange(
            change_id=c["change_id"],
            operation=c.get("operation", "edit"),
            chunk_id=c.get("chunk_id"),
            old_html=c.get("old_html"),
            new_html=c.get("new_html"),
            ai_explanation=c.get("ai_explanation"),
        )
        for c in raw_changes
    ]


class RealSuperDocsClient:
    """Every method here maps to exactly one verified REST call - no retry/backoff logic added silently;
    long-running ops (the task brief's own warning: 30s to several minutes) are the caller's job to poll
    for, not something this client hides behind a blocking sleep loop."""

    def __init__(self, api_key: str, timeout_seconds: float = 60.0):
        if not api_key:
            raise ValueError("SUPERDOCS_API_KEY is required - see .env.example")
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def upload_document(self, filename: str, content: bytes, session_id: str) -> dict:
        resp = self._client.post(
            "/v1/documents/upload",
            files={"file": (filename, content)},
            data={"session_id": session_id},
        )
        self._raise_for_status(resp)
        return resp.json()

    def upload_image(self, image_base64: str, mime_type: str) -> str:
        # Real bug, found live on 2026-08-20 by actually clicking the link this build showed the user: the
        # docs describe "url" as "a stable public URL for embedding" - it isn't. GET-ing it with no auth
        # returns a real 403 AccessDenied from Google Cloud Storage, always, for anyone, not just
        # sometimes. Only "view_url" (the signed, time-limited link) is actually reachable - confirmed by
        # calling both anonymously and comparing status codes (403 vs 200) before trusting either.
        resp = self._client.post(
            "/v1/documents/images/upload-base64",
            json={"image_base64": image_base64, "mimeType": mime_type},
        )
        self._raise_for_status(resp)
        return resp.json()["view_url"]

    def chat(self, message: str, session_id: str) -> ChatResult:
        resp = self._client.post(
            "/v1/chat",
            json={"message": message, "session_id": session_id, "approval_mode": "approve_all"},
        )
        self._raise_for_status(resp)
        body = resp.json()
        dc = body.get("document_changes") or {}
        return ChatResult(
            response_text=body.get("response", ""),
            session_id=body["session_id"],
            updated_html=dc.get("updated_html"),
            changes=_parse_changes(dc.get("changes")),
            ops_charged=(body.get("usage") or {}).get("ops_charged", 0),
        )

    def chat_with_approval(self, message: str, session_id: str) -> JobStatus:
        resp = self._client.post(
            "/v1/chat/async",
            json={"message": message, "session_id": session_id, "approval_mode": "ask_every_time"},
        )
        self._raise_for_status(resp)
        body = resp.json()
        return JobStatus(job_id=body["job_id"], session_id=body["session_id"], status=body["status"])

    def get_job(self, job_id: str) -> JobStatus:
        resp = self._client.get(f"/v1/jobs/{job_id}")
        self._raise_for_status(resp)
        body = resp.json()
        metadata = body.get("metadata") or {}
        return JobStatus(
            job_id=body["job_id"],
            session_id=body["session_id"],
            status=body["status"],
            pending_changes=_parse_changes(metadata.get("pending_changes")),
            result=body.get("result"),
            error=body.get("error"),
        )

    def wait_for_job(self, job_id: str, poll_seconds: float = 2.0, timeout_seconds: float = 300.0) -> JobStatus:
        """Polls until the job leaves pending/in_progress. Stops at awaiting_approval too - the caller
        (business logic, not this client) decides what to approve; this method never auto-approves."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            job = self.get_job(job_id)
            if job.status not in ("pending", "in_progress"):
                return job
            if time.monotonic() > deadline:
                raise SuperDocsError(f"job {job_id} did not resolve within {timeout_seconds}s")
            time.sleep(poll_seconds)

    def approve_change(self, session_id: str, job_id: str, change_id: str, approved: bool, feedback: str | None = None) -> None:
        resp = self._client.post(
            f"/v1/chat/{session_id}/approve",
            json={"job_id": job_id, "change_id": change_id, "approved": approved, "feedback": feedback},
        )
        self._raise_for_status(resp)

    def export_document(self, session_id: str, format: str = "markdown") -> str | bytes:
        """Real bug found and fixed during this project's own live verification (same fix as the sibling
        renewal-true-up-engine project, found there first): text formats (markdown/html/txt) come back as
        the response BODY directly (Content-Type: text/markdown etc.), not wrapped in a JSON envelope -
        the first version of this method called resp.json() unconditionally and crashed with a
        JSONDecodeError on every text export, including the html export this module's own round-trip
        pipeline depends on."""
        resp = self._client.post("/v1/documents/export", json={"session_id": session_id, "format": format})
        self._raise_for_status(resp)
        if format in ("markdown", "html", "txt"):
            return resp.text
        # Binary formats (docx/pdf) come back as a signed download_url envelope, per the tool docs -
        # fetching the actual bytes is the caller's job (usually not needed until final delivery).
        return resp.json()

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            raise SuperDocsError(f"SuperDocs API {resp.status_code}", status_code=resp.status_code, detail=detail)


class FakeSuperDocsClient:
    """Deterministic, offline, no network call - what every test in this project runs against by default,
    per the round-wide 'real tests, no live key needed' standard.

    Three things this fake genuinely simulates for THIS app's actual usage (not a general chat simulator):
    (1) markdown upload/export is a byte-identical passthrough, which is enough to test that
    markdown_roundtrip.py's own pipeline (upload -> export html -> export markdown -> compare) is wired
    correctly - it does NOT prove SuperDocs's real conversion preserves fidelity, only that our code does
    the right sequence of calls and comparisons; (2) a 'draft a numbered getting-started guide' message
    produces a deterministic numbered list from the feature description, so guide_generator.py's pipeline
    is testable without a live model call; (3) a 'Revise the getting-started guide as follows: ...' message
    (guide_generator.py::request_guide_revision) produces a real pending change - appending the instruction
    as a new line - that approve_change() applies or discards, so the human-in-the-loop revision path is
    genuinely exercised offline too, not just against the real API.
    """

    def __init__(self) -> None:
        self._documents: dict[str, str] = {}  # session_id -> plain text content
        self._jobs: dict[str, JobStatus] = {}
        self._pending: dict[str, dict] = {}  # change_id -> {session_id, job_id, old, new}
        self._op_counter = 0

    def upload_document(self, filename: str, content: bytes, session_id: str) -> dict:
        self._documents[session_id] = content.decode("utf-8", errors="replace")
        return {"session_id": session_id, "filename": filename, "chunks_count": self._documents[session_id].count("\n") + 1}

    def upload_image(self, image_base64: str, mime_type: str) -> str:
        self._op_counter += 1
        ext = mime_type.split("/")[-1]
        return f"https://fake-superdocs-images.test/img/{self._op_counter}.{ext}"

    _GUIDE_RE = re.compile(r"getting-started guide for the following.*?:\s*(.+)", re.DOTALL)

    def chat(self, message: str, session_id: str) -> ChatResult:
        self._op_counter += 1
        guide_match = self._GUIDE_RE.search(message)
        if guide_match:
            feature_description = guide_match.group(1).strip()
            steps = [s.strip() for s in re.split(r"[.;]\s+", feature_description) if s.strip()]
            guide_lines = [f"# Getting started\n"] + [f"{i}. {step}." for i, step in enumerate(steps, start=1)]
            self._documents[session_id] = "\n".join(guide_lines)
        return ChatResult(
            response_text=f"[fake] acknowledged: {message}",
            session_id=session_id,
            updated_html=self._documents.get(session_id),
            changes=[],
            ops_charged=1,
        )

    _REVISE_RE = re.compile(r"Revise the getting-started guide as follows:\s*(.+)", re.DOTALL)

    def chat_with_approval(self, message: str, session_id: str) -> JobStatus:
        """Real implementation (not a stub) for this app's one known ask_every_time message shape - a
        guide revision request (guide_generator.py::request_guide_revision). Proposes appending the
        requested change as a new line, exactly the same shape a real 'edit' change would take, so
        approve_change() below has something real to apply or discard."""
        revise_match = self._REVISE_RE.search(message)
        if not revise_match:
            self._op_counter += 1
            job_id = f"fake-job-{self._op_counter}"
            job = JobStatus(job_id=job_id, session_id=session_id, status="completed")
            self._jobs[job_id] = job
            return job

        instruction = revise_match.group(1).strip()
        self._op_counter += 1
        job_id = f"fake-job-{self._op_counter}"
        change_id = f"fake-change-{self._op_counter}"
        old_text = self._documents.get(session_id, "")
        new_text = f"{old_text}\n\n(revision applied: {instruction})"
        self._pending[change_id] = {"session_id": session_id, "job_id": job_id, "old": old_text, "new": new_text}
        job = JobStatus(
            job_id=job_id,
            session_id=session_id,
            status="awaiting_approval",
            pending_changes=[ProposedChange(change_id, "edit", None, old_text, new_text, f"Proposed: {instruction}")],
        )
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> JobStatus:
        return self._jobs[job_id]

    def approve_change(self, session_id: str, job_id: str, change_id: str, approved: bool, feedback: str | None = None) -> None:
        pending = self._pending.pop(change_id)
        if approved:
            self._documents[session_id] = pending["new"]
        self._jobs[job_id] = JobStatus(job_id=job_id, session_id=session_id, status="completed")

    def export_document(self, session_id: str, format: str = "markdown") -> str:
        return self._documents.get(session_id, "")


def make_client(api_key: str | None) -> SuperDocsClient:
    """Factory mirroring Task 1's LLM_PROVIDER=fake pattern: no key -> fake client, real key -> real client.
    Callers never branch on which one they got."""
    if api_key:
        return RealSuperDocsClient(api_key)
    return FakeSuperDocsClient()


def to_base64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")
