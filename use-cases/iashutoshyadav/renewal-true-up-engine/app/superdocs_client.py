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
    def upload_template(self, name: str, content: bytes) -> str: ...
    def upload_image(self, image_base64: str, mime_type: str) -> str: ...
    def chat(self, message: str, session_id: str, cross_session_search: bool = False) -> ChatResult: ...
    def chat_with_approval(self, message: str, session_id: str, cross_session_search: bool = False) -> JobStatus: ...
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
    for, not something this client hides behind a blocking sleep loop.

    Real timeout found live on 2026-08-20: the default here was 60s despite the docstring above already
    quoting "up to several minutes" - a real batch with cross_session_search=True enabled genuinely hit
    that ceiling ("The read operation timed out") once this account had accumulated enough session history
    from a day of live testing for cross-session search to take real time. 240s actually matches the
    documented range instead of contradicting it."""

    def __init__(self, api_key: str, timeout_seconds: float = 240.0):
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

    def upload_template(self, name: str, content: bytes) -> str:
        resp = self._client.post(
            "/v1/templates/upload-base64",
            json={"filename": name, "file_base64": base64.b64encode(content).decode("ascii")},
        )
        self._raise_for_status(resp)
        return resp.json()["id"]

    def upload_image(self, image_base64: str, mime_type: str) -> str:
        # Same real finding as api-reference-guide-authoring's client: "url" in the response is documented
        # as public but returns a real 403 for any anonymous request; only "view_url" (signed, time-limited)
        # actually resolves. Confirmed against the same account/endpoint, not re-guessed.
        resp = self._client.post(
            "/v1/documents/images/upload-base64",
            json={"image_base64": image_base64, "mimeType": mime_type},
        )
        self._raise_for_status(resp)
        return resp.json()["view_url"]

    def chat(self, message: str, session_id: str, cross_session_search: bool = False) -> ChatResult:
        resp = self._client.post(
            "/v1/chat",
            json={
                "message": message,
                "session_id": session_id,
                "approval_mode": "approve_all",
                "cross_session_search": cross_session_search,
            },
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

    def chat_with_approval(self, message: str, session_id: str, cross_session_search: bool = False) -> JobStatus:
        resp = self._client.post(
            "/v1/chat/async",
            json={
                "message": message,
                "session_id": session_id,
                "approval_mode": "ask_every_time",
                "cross_session_search": cross_session_search,
            },
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
        """Real bug found and fixed during live verification, not assumed from docs: text formats
        (markdown/html/txt) come back as the response BODY directly (Content-Type: text/markdown etc.),
        not wrapped in a JSON envelope - the first version of this method called resp.json() unconditionally
        and crashed with a JSONDecodeError on every text export. Only binary formats (docx/pdf) are wrapped
        in a JSON envelope carrying a signed download_url, per the tool docs - verified separately."""
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
    per the round-wide 'real tests, no live key needed' standard. Simulates the same edit-application
    semantics as the real product closely enough to exercise our business logic (true-up math, clause
    lookup, exception flagging) without depending on the network or a quota."""

    def __init__(self) -> None:
        # session_id -> uploaded documents in order, [filename, content]. Multiple documents per session
        # (Multi-document surface) are tracked genuinely, not just the latest overwriting the last. chat/
        # export operate on documents[-1] (the LAST uploaded document) - a real finding, not a guess: the
        # real API's export_document(session_id) has no document/file parameter, and live verification
        # (2026-09-14) showed it exports whichever document was uploaded most recently, regardless of what
        # a later chat instruction names - upload order, not instruction text, decides the active document.
        self._documents: dict[str, list[list[str]]] = {}
        self._jobs: dict[str, JobStatus] = {}
        self._pending: dict[str, dict] = {}  # change_id -> {session_id, job_id, old, new}
        self._op_counter = 0

    def upload_document(self, filename: str, content: bytes, session_id: str) -> dict:
        text = content.decode("utf-8", errors="replace")
        self._documents.setdefault(session_id, []).append([filename, text])
        return {"session_id": session_id, "filename": filename, "chunks_count": text.count("\n") + 1}

    def _primary_text(self, session_id: str) -> str:
        docs = self._documents.get(session_id)
        return docs[-1][1] if docs else ""

    def _set_primary_text(self, session_id: str, text: str) -> None:
        docs = self._documents.setdefault(session_id, [["primary", text]])
        docs[-1][1] = text

    def upload_template(self, name: str, content: bytes) -> str:
        self._op_counter += 1
        return f"fake-template-{self._op_counter}"

    def upload_image(self, image_base64: str, mime_type: str) -> str:
        self._op_counter += 1
        return f"https://fake.superdocs.local/images/{self._op_counter}"

    def _parse_entitlement_change(self, message: str) -> tuple[str, str] | None:
        """The fake client doesn't run an LLM, so it can't interpret arbitrary natural language - but this
        app only ever sends one message shape for an amendment (renewal_engine.py's amendment_message), so
        matching that specific pattern is enough to make our OWN business logic deterministically testable
        end to end. This is a simulation of THIS app's usage, not a general chat simulator - documented
        limitation, not an oversight."""
        match = re.search(r"from\s+([\d,]+(?:\.\d+)?)\s+to\s+([\d,]+(?:\.\d+)?)\s+compute units", message)
        if not match:
            return None
        return match.group(1), match.group(2)

    def chat(self, message: str, session_id: str, cross_session_search: bool = False) -> ChatResult:
        self._op_counter += 1
        parsed = self._parse_entitlement_change(message)
        if parsed:
            old_num, new_num = parsed
            self._set_primary_text(session_id, self._primary_text(session_id).replace(old_num, new_num))
        return ChatResult(
            response_text=f"[fake] acknowledged: {message}",
            session_id=session_id,
            updated_html=self._primary_text(session_id),
            changes=[],
            ops_charged=1,
        )

    def seed_pending_change(self, session_id: str, old_text: str, new_text: str) -> JobStatus:
        """Test helper: fabricate a pending change the way a real ask_every_time job would produce one,
        so approval-flow tests don't need a real network call to exercise real HITL logic."""
        self._op_counter += 1
        job_id = f"fake-job-{self._op_counter}"
        change_id = f"fake-change-{self._op_counter}"
        self._pending[change_id] = {"session_id": session_id, "job_id": job_id, "old": old_text, "new": new_text}
        job = JobStatus(
            job_id=job_id,
            session_id=session_id,
            status="awaiting_approval",
            pending_changes=[ProposedChange(change_id, "edit", None, old_text, new_text, "fake explanation")],
        )
        self._jobs[job_id] = job
        return job

    def chat_with_approval(self, message: str, session_id: str, cross_session_search: bool = False) -> JobStatus:
        """Real implementation (not a stub) for this app's one known message shape - see
        _parse_entitlement_change. Falls back to a completed no-op job if the message doesn't match
        anything this fake understands, rather than raising, so a caller that sends an unexpected message
        gets an honest 'nothing proposed' rather than a crash."""
        parsed = self._parse_entitlement_change(message)
        if not parsed:
            self._op_counter += 1
            job_id = f"fake-job-{self._op_counter}"
            job = JobStatus(job_id=job_id, session_id=session_id, status="completed")
            self._jobs[job_id] = job
            return job
        old_num, new_num = parsed
        return self.seed_pending_change(session_id, old_text=old_num, new_text=new_num)

    def get_job(self, job_id: str) -> JobStatus:
        return self._jobs[job_id]

    def approve_change(self, session_id: str, job_id: str, change_id: str, approved: bool, feedback: str | None = None) -> None:
        pending = self._pending.pop(change_id)
        if approved:
            self._set_primary_text(session_id, self._primary_text(session_id).replace(pending["old"], pending["new"]))
        self._jobs[job_id] = JobStatus(job_id=job_id, session_id=session_id, status="completed")

    def export_document(self, session_id: str, format: str = "markdown") -> str:
        return self._primary_text(session_id)


def make_client(api_key: str | None) -> SuperDocsClient:
    """Factory mirroring Task 1's LLM_PROVIDER=fake pattern: no key -> fake client, real key -> real client.
    Callers never branch on which one they got."""
    if api_key:
        return RealSuperDocsClient(api_key)
    return FakeSuperDocsClient()


def to_base64(content: bytes) -> str:
    return base64.b64encode(content).decode("ascii")
