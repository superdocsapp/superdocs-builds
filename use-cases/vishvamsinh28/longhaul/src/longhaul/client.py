"""SuperDocs REST client.

Deliberately thin. The one design rule that matters: **this client never retries a
call that can create an edit.** A transport error on ``POST /v1/chat/async`` is
ambiguous — the request may have reached the server and the response may have been
lost on the way back — and retrying an ambiguous edit is exactly the double-apply this
project exists to prevent. Ambiguity is handed up to :mod:`longhaul.reconcile`, which
resolves it against durable server state instead of guessing.

Safe reads (``GET``) and the approve call *are* retried, because replaying them cannot
create an edit that did not already exist as a proposal. See CONTRACT.md, windows W1/W2.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.superdocs.app"

#: Job states from which a job will not move on its own.
SETTLED_JOB_STATES = frozenset({"completed", "failed", "cancelled"})


@dataclass(frozen=True)
class ApiCall:
    """One request that actually went to SuperDocs.

    Recorded so an operator can see the integration working rather than take it on
    trust: method, path, status, duration, and what it cost.
    """

    seq: int
    method: str
    path: str
    status: int | None
    ms: int
    at: float
    note: str = ""
    billable: bool = False
    error: str | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "seq": self.seq, "method": self.method, "path": self.path,
            "status": self.status, "ms": self.ms, "at": self.at,
            "note": self.note, "billable": self.billable, "error": self.error,
        }


class CallLog:
    """A bounded, thread-safe record of recent API calls."""

    def __init__(self, limit: int = 400) -> None:
        self._calls: deque[ApiCall] = deque(maxlen=limit)
        self._lock = threading.Lock()
        self._seq = 0

    def record(
        self, method: str, path: str, status: int | None, ms: int,
        *, note: str = "", billable: bool = False, error: str | None = None,
    ) -> None:
        with self._lock:
            self._seq += 1
            self._calls.append(ApiCall(
                seq=self._seq, method=method, path=path, status=status, ms=ms,
                at=time.time(), note=note, billable=billable, error=error,
            ))

    def since(self, seq: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [c.to_public() for c in self._calls if c.seq > seq]

    def total(self) -> int:
        with self._lock:
            return self._seq


class SuperDocsError(RuntimeError):
    """An error that names its cause and, where possible, its fix."""

    def __init__(self, message: str, *, status: int | None = None, fix: str = "") -> None:
        super().__init__(message if not fix else f"{message}\n  fix: {fix}")
        self.status = status
        self.fix = fix


class AmbiguousRequest(SuperDocsError):
    """A request may or may not have reached the server.

    Never resolved by retrying. The runner reconciles it against server state.
    """


class SessionBusy(SuperDocsError):
    """The session has changes staged for review and will not take a new instruction.

    Discovered against the live API, which enforces one pending review per session. It is
    not an error so much as a fact: some earlier turn is still waiting on a decision, and
    it has to be settled before another turn can be issued.
    """


class RateLimited(SuperDocsError):
    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message, status=429, fix=f"wait {retry_after:.0f}s and resume")
        self.retry_after = retry_after


@dataclass(frozen=True)
class UploadResult:
    document_id: str
    html: str
    chunks_count: int
    version_id: str | None
    title: str


@dataclass(frozen=True)
class Job:
    job_id: str
    status: str
    metadata: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None

    @property
    def awaiting_kind(self) -> str | None:
        return self.metadata.get("awaiting_kind")

    @property
    def is_settled(self) -> bool:
        return self.status in SETTLED_JOB_STATES

    def pending_changes(self) -> list[dict[str, Any]]:
        """Proposed changes on a HITL pause.

        Handles the documented trap: proposed-change payloads can arrive as a
        JSON-encoded *string* that needs a second parse. Integrators who miss this see
        diff cards where every field reads ``undefined``.
        """
        return parse_changes(self.metadata.get("pending_changes"))


def parse_changes(raw: Any) -> list[dict[str, Any]]:
    """Normalise a proposed-change payload into a list of dicts.

    Handles the documented trap: the content can arrive as a JSON-encoded string inside
    JSON and needs a second parse. Missing it is the single most common reason integrators
    see diff cards where every field reads undefined.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        raw = raw.get("changes", [])
        if isinstance(raw, str):  # doubly-encoded; parse again
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return []
    return [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []


class SuperDocsClient:
    """The four-call contract (upload, chat, approve, export) plus the reads that
    make crash recovery possible (job status, session history, document roster)."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
        call_log: CallLog | None = None,
    ) -> None:
        self.call_log = call_log
        self.api_key = api_key
        if not api_key:
            raise SuperDocsError(
                "no API key",
                fix="set SUPERDOCS_API_KEY in your environment or .env file",
            )
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SuperDocsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- plumbing ---------------------------------------------------------

    @contextmanager
    def _timed(self, method: str, path: str, note: str = "", billable: bool = False):
        """Time one call and record it, whether it succeeds or not."""
        started = time.monotonic()
        holder: dict[str, Any] = {"status": None}
        try:
            yield holder
        except SuperDocsError as exc:
            if self.call_log:
                self.call_log.record(
                    method, path, exc.status, int((time.monotonic() - started) * 1000),
                    note=note, error=str(exc).split("\n")[0],
                )
            raise
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised unchanged
            if self.call_log:
                self.call_log.record(
                    method, path, None, int((time.monotonic() - started) * 1000),
                    note=note, error=f"{type(exc).__name__}: {exc}",
                )
            raise
        if self.call_log:
            self.call_log.record(
                method, path, holder.get("status"),
                int((time.monotonic() - started) * 1000), note=note, billable=billable,
            )

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code < 400:
            return r
        detail = _detail(r)
        if r.status_code == 401:
            raise SuperDocsError(
                f"401 unauthorized: {detail}",
                status=401,
                fix="the header value is just sk_... with no 'Bearer ' inside it, and "
                    "/v1/users/* endpoints reject API keys by design",
            )
        if r.status_code == 429:
            raise RateLimited(f"429 rate limited: {detail}",
                              float(r.headers.get("Retry-After", "60")))
        if r.status_code == 409:
            if "session_busy" in detail or "waiting for your review" in detail:
                raise SessionBusy(
                    f"409 session busy: {detail}", status=409,
                    fix="decide the changes already staged on this session, then retry",
                )
            raise SuperDocsError(
                f"409 conflict: {detail}", status=409,
                fix="a chat job is in flight on this session; let it settle or cancel it",
            )
        if r.status_code == 413:
            raise SuperDocsError(
                f"413 too large: {detail}", status=413,
                fix="split the work across smaller turns, or request a limit raise",
            )
        raise SuperDocsError(f"{r.status_code} from {r.request.url.path}: {detail}",
                             status=r.status_code)

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        """GET with bounded retry. Safe: a GET cannot create an edit."""
        last: Exception | None = None
        for attempt in range(4):
            try:
                with self._timed("GET", path, note="read (free)") as t:
                    r = self._check(self._client.get(path, **kwargs))
                    t["status"] = r.status_code
                return r
            except RateLimited as exc:
                last = exc
                time.sleep(min(exc.retry_after, 30.0))
            except (httpx.TransportError, SuperDocsError) as exc:
                if isinstance(exc, SuperDocsError) and exc.status not in (None, 500, 502, 503, 504):
                    raise
                last = exc
                time.sleep(0.25 * (2 ** attempt))
        raise SuperDocsError(f"GET {path} failed after 4 attempts: {last}")

    # --- 1. upload --------------------------------------------------------

    def upload_document(
        self, session_id: str, path: str | Path, *, open_mode: str = "background"
    ) -> UploadResult:
        """Upload a file as a document in the session.

        ``open_mode=background`` opens it as an additional document without stealing
        focus, which is what a multi-document job wants: every document open at once,
        each targeted explicitly by id.
        """
        p = Path(path)
        try:
            with p.open("rb") as fh, self._timed(
                "POST", "/v1/documents/upload", note=f"upload {p.name} (free)"
            ) as t:
                r = self._check(self._client.post(
                    "/v1/documents/upload",
                    files={"file": (p.name, fh, _mime_for(p))},
                    data={"session_id": session_id, "open_mode": open_mode},
                ))
                t["status"] = r.status_code
        except httpx.TransportError as exc:
            # Not retried here. The caller checks the session roster before uploading, so
            # a document that did land is adopted on the next attempt rather than opened
            # a second time.
            raise SuperDocsError(
                f"could not reach {self.base_url} to upload {p.name}: {exc}",
                fix="check SUPERDOCS_BASE_URL and your network, then run the job again — "
                    "an upload that already landed is adopted, not repeated",
            ) from exc
        body = r.json()
        doc_id = body.get("document_id") or _focused_id(body) or ""
        return UploadResult(
            document_id=doc_id,
            html=body.get("html", ""),
            chunks_count=body.get("chunks_count", 0),
            version_id=body.get("version_id"),
            title=body.get("title") or p.stem,
        )

    # --- 2. chat ----------------------------------------------------------

    def chat_async(
        self,
        session_id: str,
        message: str,
        *,
        document_id: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
    ) -> str:
        """Start an async edit turn. Returns the ``job_id``.

        **Not retried, ever.** A transport error here is raised as
        :class:`AmbiguousRequest` and resolved by reconciliation, because a retry that
        guesses wrong applies the edit twice.
        """
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
        }
        if document_id:
            payload["document_id"] = document_id
        if model_tier:
            payload["model_tier"] = model_tier
        try:
            with self._timed(
                "POST", "/v1/chat/async", note="edit turn", billable=True
            ) as t:
                r = self._check(self._client.post("/v1/chat/async", json=payload))
                t["status"] = r.status_code
        except httpx.TransportError as exc:
            raise AmbiguousRequest(
                f"chat request may or may not have reached the server: {exc}",
                fix="do not retry; reconcile against session history",
            ) from exc
        return r.json()["job_id"]

    def get_job(self, job_id: str) -> Job | None:
        """Poll one job. ``None`` means the job is gone — jobs are purged one hour
        after creation, so this is expected on a long outage, not an error."""
        try:
            r = self._get(f"/v1/jobs/{job_id}")
        except SuperDocsError as exc:
            if exc.status == 404:
                return None
            raise
        body = r.json()
        return Job(
            job_id=body.get("job_id", job_id),
            status=body.get("status", "unknown"),
            metadata=body.get("metadata") or {},
            result=body.get("result"),
            error=body.get("error"),
        )

    def wait_for_job(
        self,
        job_id: str,
        *,
        until: frozenset[str],
        max_wait: float = 900.0,
        poll_interval: float = 1.0,
        on_wait: Any = None,
    ) -> Job:
        """Poll until the job reaches one of ``until`` (or settles).

        Long silences are normal here: a full-document turn can run for minutes with no
        visible progress. That is still processing, not a crash.
        """
        deadline = time.monotonic() + max_wait
        interval = poll_interval
        while True:
            job = self.get_job(job_id)
            if job is None:
                raise SuperDocsError(
                    f"job {job_id} no longer exists",
                    status=404,
                    fix="jobs are purged 1h after creation; reconcile against session history",
                )
            if job.status in until or job.is_settled:
                return job
            if time.monotonic() > deadline:
                raise SuperDocsError(
                    f"job {job_id} still {job.status} after {max_wait:.0f}s",
                    fix="large documents can take up to 30 minutes; raise max_wait or split the step",
                )
            if on_wait:
                on_wait(job)
            time.sleep(interval)
            # Back off toward a few seconds. A turn runs for tens of seconds, so asking
            # every second is a lot of requests to learn nothing.
            interval = min(interval * 1.4, 4.0)

    # --- 3. approve -------------------------------------------------------

    def approve(
        self,
        session_id: str,
        job_id: str,
        decisions: list[tuple[str, bool, str | None]],
    ) -> dict[str, Any]:
        """Commit per-change decisions.

        Safe to replay: every entry names a ``change_id`` that already exists as a
        proposal, so replaying can only re-assert a decision, never invent an edit.

        Note the documented trap — top-level ``approved`` is required even when every
        entry carries its own, or the endpoint answers 422.
        """
        changes = [
            {"change_id": cid, "approved": ok, **({"feedback": fb} if fb else {})}
            for cid, ok, fb in decisions
        ]
        payload = {
            "job_id": job_id,
            "approved": any(ok for _, ok, _ in decisions),
            "changes": changes,
        }
        approved_n = sum(1 for _, ok, _ in decisions if ok)
        last: Exception | None = None
        for attempt in range(3):
            try:
                with self._timed(
                    "POST", f"/v1/chat/{session_id}/approve",
                    note=f"commit {approved_n}/{len(decisions)} changes",
                ) as t:
                    r = self._check(
                        self._client.post(f"/v1/chat/{session_id}/approve", json=payload)
                    )
                    t["status"] = r.status_code
                return r.json()
            except (httpx.TransportError, RateLimited) as exc:
                last = exc
                time.sleep(0.5 * (2 ** attempt))
        raise SuperDocsError(f"approve failed after 3 attempts: {last}")

    # --- 4. export --------------------------------------------------------

    def export(
        self,
        *,
        session_id: str | None = None,
        html: str | None = None,
        fmt: str = "docx",
        options: dict[str, Any] | None = None,
    ) -> bytes:
        """Export a document. Exports never cost operations, so they are cheap to repeat.

        The endpoint takes ``html``, ``session_id`` or ``upload_id`` — and nothing that
        names one document of a multi-document session. Exporting by ``session_id``
        returns whichever document is *focused*. To export a specific one, use
        :meth:`export_document`.
        """
        payload: dict[str, Any] = {"format": fmt}
        if session_id:
            payload["session_id"] = session_id
        if html is not None:
            payload["html"] = html
        if options:
            payload["options"] = options
        with self._timed(
            "POST", "/v1/documents/export", note=f"export {fmt} (free)"
        ) as t:
            r = self._check(self._client.post("/v1/documents/export", json=payload))
            t["status"] = r.status_code
        return r.content

    def export_document(
        self,
        session_id: str,
        document_id: str,
        *,
        fmt: str = "docx",
        options: dict[str, Any] | None = None,
    ) -> bytes:
        """Export one named document from a multi-document session.

        There is no per-document selector on the export endpoint, and passing one is
        accepted and then ignored — every document comes back as the focused one. So the
        document's HTML is read from the session roster and exported directly. Both calls
        are free, and unlike switching focus this mutates nothing.
        """
        for entry in self.session_documents(session_id, include_html=True):
            if entry.get("document_id") == document_id:
                html = entry.get("html")
                if not html:
                    raise SuperDocsError(
                        f"document {document_id} came back from the roster with no HTML",
                        fix="retry; if it persists the document may still be processing",
                    )
                return self.export(html=html, fmt=fmt, options=options)
        raise SuperDocsError(
            f"document {document_id} is not open in session {session_id}",
            fix="the run's documents must stay open in its session for the whole job",
        )

    # --- reads that make recovery possible --------------------------------

    def session_history(
        self, session_id: str, *, include_document_html: bool = False
    ) -> dict[str, Any]:
        """The durable transcript. Unlike jobs, this does not expire, which is what
        makes at-most-once hold across an outage longer than the one-hour job TTL."""
        r = self._get(
            f"/v1/sessions/{session_id}/history",
            params={"include_document_html": str(include_document_html).lower()},
        )
        return r.json()

    def session_jobs(self, session_id: str) -> list[dict[str, Any]]:
        """Jobs belonging to one session, most recent first.

        The recovery route for the nastiest crash in the system: killed after the chat
        request went out but before its ``job_id`` reached the ledger. The turn exists on
        the server and we have no handle to it. Listing the session's jobs gives the
        handle back, so the turn can be adopted instead of issued a second time.
        """
        r = self._get(f"/v1/sessions/{session_id}/jobs")
        body = r.json()
        jobs = body.get("jobs", body) if isinstance(body, dict) else body
        return jobs if isinstance(jobs, list) else []

    def session_documents(
        self, session_id: str, *, include_html: bool = False
    ) -> list[dict[str, Any]]:
        r = self._get(
            f"/v1/sessions/{session_id}/documents",
            params={"include_html": str(include_html).lower()},
        )
        body = r.json()
        docs = body.get("documents", body) if isinstance(body, dict) else body
        return docs if isinstance(docs, list) else []

    def ping(self) -> bool:
        """Cheapest possible key check: GET /v1/sessions costs no operations."""
        self._get("/v1/sessions")
        return True


def _detail(r: httpx.Response) -> str:
    try:
        body = r.json()
    except (json.JSONDecodeError, ValueError):
        return r.text[:300]
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error") or body
        if isinstance(detail, dict):
            # Structured errors carry an error_code and a human message; keep both, since
            # the code is what callers branch on and the message is what a person reads.
            parts = [str(detail.get(k)) for k in ("error_code", "message", "suggested_action")
                     if detail.get(k)]
            return " | ".join(parts)[:400] if parts else str(detail)[:400]
        return str(detail)[:300]
    return str(body)[:300]


def _focused_id(body: dict[str, Any]) -> str | None:
    for doc in body.get("documents", []) or []:
        if doc.get("focused") or doc.get("is_focused"):
            return doc.get("document_id") or doc.get("id")
    return None


_MIME = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".rtf": "application/rtf",
}


def _mime_for(p: Path) -> str:
    return _MIME.get(p.suffix.lower(), "application/octet-stream")
