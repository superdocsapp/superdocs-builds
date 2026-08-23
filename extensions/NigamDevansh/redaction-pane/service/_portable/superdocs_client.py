# ─────────────────────────────────────────────────────────────────────
# COPIED FILE — do not edit here.
# Source: packages/core/src/doctask_core/portable/superdocs_client.py
# Refresh: uv run python scripts/sync_portable.py
# This app is standalone by design and imports nothing outside itself.
# ─────────────────────────────────────────────────────────────────────
"""SuperDocs REST client.

PORTABLE: zero internal imports. httpx + standard library only.
Source of truth. Copies live in each extension's `_portable/`.

Three constraints shape this file, all of them consequences of it being copied
into someone else's repository:

  * errors are declared **here**, not imported from `doctask_core.errors`
  * telemetry is a **callback**, not a Protocol we would have to import
  * config arrives as **arguments**, never read from the environment

See docs/CORE_INTERNALS.md § "portable/superdocs_client.py".
"""

from __future__ import annotations

import base64
import binascii
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

# ── errors, declared inline ───────────────────────────────────────────────
# Mirrors the SuperDocsError branch of doctask_core.errors. The worker maps
# between the two; extensions use these directly.


class SuperDocsError(Exception):
    """Base for every failure this client raises."""


class SuperDocsUnavailable(SuperDocsError):
    """Transient, retries exhausted."""


class QuotaExhausted(SuperDocsError):
    """429 monthly limit. Not retried."""


class SuperDocsConflict(SuperDocsError):
    """409 — document in use or concurrent edit."""


class SuperDocsRejected(SuperDocsError):
    """Other 4xx — our request is wrong."""


class SuperDocsAmbiguous(SuperDocsError):
    """Cannot determine whether the job started. Never relaunch blind."""


# ── value objects ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class UsageRecord:
    """One billable interaction, handed to the `on_usage` callback."""

    operation: str
    ops_charged: int
    ops_remaining: int | None
    ops_limit: int | None
    model_tier: str


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Both ids, because the API returns the wrong one by default.

    `POST /v1/documents/upload` returns `document_id: "doc_primary"` — a
    session-local slot reused by the next upload, so storing it and dereferencing
    later resolves to whatever now occupies it. The durable id comes only from
    `GET /v1/sessions/{id}/documents`; the client makes that free call so no
    caller can persist the slot id.
    """

    durable_document_id: str
    """Stable across uploads and sessions. This is what we store."""
    slot_id: str
    """`doc_primary` etc. Valid only within this session, right now."""
    filename: str
    session_id: str
    html: str
    """The upload response already carries the parsed document as HTML with a
    `data-chunk-id` on every block — no separate parse call is needed."""
    chunks_count: int
    page_setup: dict[str, Any] = field(default_factory=dict)
    """Real paper size, margins and orientation from the source `.docx`. The API
    carries no page or line numbers, so anything showing a document as pages must
    paginate itself, and the wrong paper size misplaces every page break. Empty
    for a format with no page setup (`.md`), so the caller falls back."""


@dataclass(frozen=True, slots=True)
class JobHandle:
    job_id: str
    session_id: str
    status: str


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    status: Literal[
        "pending",
        "in_progress",
        "awaiting_approval",
        "completed",
        "failed",
        "cancelled",
    ]
    """Exactly the states the recorded fixtures show. `awaiting_approval` is where
    the human gate lives — a client that cannot name it cannot wait on it."""
    metadata: dict[str, Any] = field(default_factory=dict)
    """`metadata['pending_changes']` is a real JSON array here. The "parse it
    twice" gotcha belongs to the SSE path, where `proposed_change_batch.content`
    decodes to a batch envelope, not a bare list — use `parse_pending_changes`
    here, `parse_proposed_change_batch` on the event."""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ChangeDecision:
    change_id: str
    """Keyed by `change_id`, not `chunk_id`: one chunk can carry more than one
    proposed change in a turn, so approving by chunk id would silently approve
    more than was decided."""
    approved: bool
    feedback: str | None = None
    """Sent on a rejection so the AI can revise. The polling loop must expect
    another `awaiting_approval` round rather than assuming one."""


@dataclass(frozen=True, slots=True)
class ApproveResult:
    """The **wire response**, nothing more.

    Recorded: `{"status": "ok", "batch_complete": true}`. An earlier version
    declared approved/rejected/remaining counts the API never returns —
    inventing response fields is how a client reads zeros and reports nothing
    approved. `batch_complete=False` means another `awaiting_approval` round is
    coming. Counts, if wanted, come from the decisions we submitted, as our
    telemetry, never as an API response.
    """

    status: str
    batch_complete: bool
    message: str = ""


@dataclass(frozen=True, slots=True)
class PendingChange:
    """One proposed edit, awaiting a human. `old_html`/`new_html` are verbatim
    because the review shows the diff and the verifier re-reads what was written
    — summarising them would mean the approved thing is not the thing we hold."""

    change_id: str
    operation: str
    chunk_id: str
    old_html: str = ""
    new_html: str = ""
    ai_explanation: str = ""
    document_id: str = ""


@dataclass(frozen=True, slots=True)
class Quota:
    """From `GET /v1/agents/whoami` — the ONE place quota was observed. No edit or
    upload response carries a `usage` object, so a parser looking for one would
    report zero and park a pile that had budget. Checked before a run, not
    during."""

    tier: str
    monthly_limit: int
    used: int
    remaining: int
    resets_at: str = ""


@dataclass(frozen=True, slots=True)
class Part:
    """An out-of-flow block: header, footer, footnote body or comment — where PII
    hides. Ordinary editable blocks carrying `data-part-type`, redacted through
    the same approval path as body text."""

    part_type: str
    chunk_id: str
    preview: str
    section: str = ""
    variant: str = ""


@dataclass(frozen=True, slots=True)
class Structure:
    """The free read, via `GET /v1/documents/{durable_id}` — there is no separate
    `/structure` endpoint. Our verification primitive: `block_count` before and
    after an edit detects structural damage at zero cost."""

    headings: list[dict[str, Any]]
    """Only populated from real Word heading styles. A `.pdf` or plain-text
    source yields an empty list — verified."""
    section_count: int
    """Heading-anchored when headings exist; falls back to block count."""
    block_count: int
    media: dict[str, int]
    parts: list[Part]
    """Empty unless the document actually carries headers/footers/comments."""


@dataclass(frozen=True, slots=True)
class ExportResult:
    content: bytes
    filename: str
    content_type: str
    warnings: list[str] = field(default_factory=list)
    """Decoded from the base64 `X-Export-Warnings` header. Always surfaced —
    an export that silently dropped formatting is a lie by omission."""


# ── wire parsing ──────────────────────────────────────────────────────────
# Pure functions: JSON in, value object out. No transport, clock or environment,
# so each is tested against the recorded responses in `fixtures/` with no key.
# The rule: never read a field no recorded response contains — an earlier
# ApproveResult declared counts the API omits, which reads as "nothing approved".


class MalformedResponse(SuperDocsRejected):
    """The response parsed as JSON but is missing something we require. A subclass
    of `SuperDocsRejected`: to the caller an unusable response and a refused
    request are the same event — this exchange cannot proceed."""


def _require(body: dict[str, Any], key: str, where: str) -> Any:
    if key not in body:
        raise MalformedResponse(f"{where}: response has no {key!r} (keys: {sorted(body)})")
    return body[key]


def parse_upload(
    upload_body: dict[str, Any], session_documents_body: dict[str, Any]
) -> UploadResult:
    """Two responses, one object — and that is the whole point.

    `POST /v1/documents/upload` returns `document_id: "doc_primary"`, a
    session-local slot. The durable id exists only in
    `GET /v1/sessions/{id}/documents`. Requiring both bodies here means there is
    no way to build an `UploadResult` from the upload alone and accidentally
    persist the slot id.
    """
    session_id = _require(upload_body, "session_id", "upload")
    slot_id = _require(upload_body, "document_id", "upload")

    # The slot id is `doc_primary` in EVERY session, so matching on it alone
    # will happily resolve against a listing for some other session and hand
    # back a durable id pointing at a different document. Nothing downstream
    # could detect that: the id is well-formed, the document exists, and every
    # citation and redaction target we store afterwards points at the wrong
    # file. Checked here because this is the only place both bodies are held.
    listing_session = session_documents_body.get("session_id")
    if listing_session != session_id:
        raise MalformedResponse(
            f"upload: document listing is for session {listing_session!r}, "
            f"but the upload was to {session_id!r} — refusing to resolve "
            f"{slot_id!r} against another session's documents"
        )

    for doc in session_documents_body.get("documents", []):
        if doc.get("document_id") == slot_id and doc.get("durable_document_id"):
            durable = str(doc["durable_document_id"])
            break
    else:
        raise MalformedResponse(
            f"upload: no durable_document_id for slot {slot_id!r} in session {session_id!r} — "
            "refusing to return the slot id as if it were durable"
        )

    return UploadResult(
        durable_document_id=durable,
        slot_id=str(slot_id),
        filename=str(upload_body.get("filename", "")),
        session_id=str(session_id),
        html=str(upload_body.get("html") or ""),
        chunks_count=int(upload_body.get("chunks_count") or 0),
        page_setup=dict(upload_body.get("page_setup") or {}),
    )


def parse_job(body: dict[str, Any]) -> Job:
    """`GET /v1/jobs/{id}`. An unrecognised status is passed through, not mapped
    to `failed` — inventing a terminal state for a running job is how a caller
    abandons work the platform is still doing."""
    return Job(
        job_id=str(_require(body, "job_id", "job")),
        status=str(_require(body, "status", "job")),  # type: ignore[arg-type]
        metadata=dict(body.get("metadata") or {}),
        error=body.get("error"),
    )


def _changes_from(payload: Any, where: str) -> list[PendingChange]:
    """Normalise every shape the two transports produce into one list: a bare
    list (polling), a JSON string wrapping one (the double encoding), or a batch
    envelope `{"changes": [...]}` (the SSE event). The envelope is the one an
    earlier parser missed — it read "JSON-encoded batch" as "JSON-encoded list"
    and rejected its own fixture."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise MalformedResponse(f"{where}: string form is not JSON — {exc}") from exc

    if payload is None:
        return []
    if isinstance(payload, dict):
        if "changes" not in payload:
            raise MalformedResponse(f"{where}: object has no 'changes' (keys: {sorted(payload)})")
        payload = payload["changes"]
    if not isinstance(payload, list):
        raise MalformedResponse(f"{where}: expected a list, got {type(payload).__name__}")

    return [
        PendingChange(
            change_id=str(_require(item, "change_id", where)),
            operation=str(item.get("operation", "")),
            chunk_id=str(item.get("chunk_id", "")),
            old_html=str(item.get("old_html") or ""),
            new_html=str(item.get("new_html") or ""),
            ai_explanation=str(item.get("ai_explanation") or ""),
            document_id=str(item.get("document_id") or ""),
        )
        for item in payload
    ]


def parse_pending_changes(metadata: dict[str, Any]) -> list[PendingChange]:
    """The POLLING path: `GET /v1/jobs/{id}` → `metadata['pending_changes']`.

    Verified 2026-08-10 to be a real JSON **array** here — the documented "parse
    it twice" gotcha does not reproduce on this transport, and a parser that
    assumed the string form would break the path used most. The string and
    envelope shapes are accepted anyway, because being lenient about what
    arrives costs nothing and the two transports have already disagreed once.
    """
    return _changes_from(metadata.get("pending_changes"), "pending_changes")


def parse_proposed_change_batch(event: dict[str, Any]) -> list[PendingChange]:
    """The SSE path: one `proposed_change_batch` event.

    `content` is a JSON-encoded **batch envelope**, not a bare list — this is
    where the double parse is real. Kept as its own function rather than folded
    into `parse_pending_changes` because the caller genuinely has a different
    object in hand, and naming that makes the two transports visible at the
    call site instead of hidden behind a permissive parameter.
    """
    kind = event.get("type")
    if kind != "proposed_change_batch":
        raise MalformedResponse(
            f"proposed_change_batch: event type is {kind!r}, not 'proposed_change_batch'"
        )
    return _changes_from(event.get("content"), "proposed_change_batch")


def parse_approve_result(body: dict[str, Any]) -> ApproveResult:
    """`{"status": "ok", "message": "...", "batch_complete": true}` — all of it.

    `batch_complete` defaults to False when absent: assuming a batch finished
    when the API did not say so ends the polling loop while the AI is still
    revising, and the run reports success having applied part of the change.
    """
    return ApproveResult(
        status=str(_require(body, "status", "approve")),
        batch_complete=bool(body.get("batch_complete", False)),
        message=str(body.get("message") or ""),
    )


def parse_structure(body: dict[str, Any]) -> Structure:
    """Accepts the full `GET /v1/documents/{durable_id}` body or its bare
    `structure` block — the document detail when reading, the block alone when
    re-reading to verify an edit."""
    block = body.get("structure") if "structure" in body else body
    if not isinstance(block, dict):
        raise MalformedResponse("structure: no structure block in response")

    parts = [
        Part(
            part_type=str(p.get("part_type", "")),
            chunk_id=str(p.get("chunk_id", "")),
            preview=str(p.get("preview", "")),
            section=str(p.get("section", "")),
            variant=str(p.get("variant", "")),
        )
        for p in block.get("parts", [])
    ]
    return Structure(
        headings=list(block.get("headings") or []),
        section_count=int(block.get("section_count") or 0),
        block_count=int(_require(block, "block_count", "structure") or 0),
        media=dict(block.get("media") or {}),
        parts=parts,
    )


def parse_quota(whoami_body: dict[str, Any]) -> Quota:
    """`GET /v1/agents/whoami`. Free, and the only endpoint that reports quota."""
    q = _require(whoami_body, "quota", "whoami")
    return Quota(
        tier=str(q.get("tier", whoami_body.get("tier", ""))),
        monthly_limit=int(_require(q, "monthly_limit", "whoami.quota")),
        used=int(_require(q, "used", "whoami.quota")),
        remaining=int(_require(q, "remaining", "whoami.quota")),
        resets_at=str(q.get("resets_at") or ""),
    )


def decode_export_warnings(header_value: str | None) -> list[str]:
    """`X-Export-Warnings`: base64-encoded JSON, absent on a clean export. Never
    raises — an unreadable header must not fail an otherwise-good export, but must
    not vanish either, so it is surfaced as a warning about itself."""
    if not header_value:
        return []
    try:
        decoded = base64.b64decode(header_value, validate=True).decode("utf-8")
        parsed = json.loads(decoded)
    except (binascii.Error, ValueError):
        return [f"X-Export-Warnings could not be decoded: {header_value[:120]}"]
    if isinstance(parsed, list):
        return [str(w) for w in parsed]
    return [str(parsed)]


# ── the client ────────────────────────────────────────────────────────────


TERMINAL_JOB_STATES = frozenset({"completed", "failed", "cancelled"})
"""States a job never leaves. `awaiting_approval` is deliberately NOT here — it
is where the human gate lives, and a poller that treated it as terminal would
walk away from a turn waiting on a decision."""

RETRYABLE_STATUS = frozenset({502, 503, 504})
MAX_ATTEMPTS = 3
BASE_BACKOFF_S = 0.5
MAX_JOB_WAIT_S = 900.0


class SuperDocsClient:
    """Synchronous. Owned by the worker process; never called from the API.

    There is no `create_session` method, and that is not an omission: sessions
    auto-start on first use of any new id string. We pass `pile_id` and there
    is nothing to create.

    Every method maps a transport failure onto one of the errors declared at
    the top of this file, so a caller never catches an `httpx` exception. That
    is what makes this file copyable: an extension that vendors it inherits the
    error contract, not our dependency tree.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_tier: str = "core",
        thinking_depth: str = "balanced",
        timeout_s: float = 120.0,
        on_usage: Callable[[UsageRecord], None] | None = None,
        transport: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key:
            raise SuperDocsRejected("SuperDocsClient: an API key is required")
        import httpx

        self.base_url = base_url.rstrip("/")
        self.model_tier = model_tier
        self.thinking_depth = thinking_depth
        self.timeout_s = timeout_s
        self._on_usage = on_usage
        self._sleep = sleep
        self._now = now
        """Injected, so tests assert the wait rather than take it — the same
        shape as the LLM client's backoff."""
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> SuperDocsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── transport ─────────────────────────────────────────────────────────
    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_safe: bool = True,
        operation: str = "",
        **kwargs: Any,
    ) -> Any:
        """One call, with the retry policy from CORE_INTERNALS §5. `retry_safe=
        False` is for requests that may have taken effect before we stopped
        hearing about them: a read timeout on `chat_async` means the edit is
        possibly running, so retrying would launch a second one — it raises
        `SuperDocsAmbiguous` and the graph parks. "Never relaunch blind."
        """
        import httpx

        where = operation or path
        last: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.ConnectError as exc:
                # The one definitely pre-connection failure: the request never
                # left, so nothing happened server-side. Safe to retry.
                last = exc
                self._wait(attempt)
                continue
            except httpx.HTTPError as exc:
                # Everything else can occur AFTER the request was sent.
                if not retry_safe:
                    raise SuperDocsAmbiguous(_ambiguous(where, type(exc).__name__)) from exc
                last = exc
                self._wait(attempt)
                continue

            if response.status_code in RETRYABLE_STATUS:
                # A 502/503/504 reached a gateway, and may have reached SuperDocs
                # behind it — the same unknown as a read timeout for an unsafe
                # call, so the same answer. Treating it as "nothing happened" is
                # how a retry becomes a second edit.
                if not retry_safe:
                    raise SuperDocsAmbiguous(_ambiguous(where, f"HTTP {response.status_code}"))
                last = SuperDocsUnavailable(f"{where}: HTTP {response.status_code}")
                self._wait(attempt)
                continue

            self._raise_for_status(response, where)
            return response

        raise SuperDocsUnavailable(
            f"{where}: failed after {MAX_ATTEMPTS} attempts — {last}"
        ) from last

    def _wait(self, attempt: int) -> None:
        """Jittered, and stops after the last attempt. Jitter, or several workers
        retry an outage in lockstep and arrive together. No sleep after the final
        failure — it delays the answer without buying a try."""
        if attempt + 1 >= MAX_ATTEMPTS:
            return
        self._sleep(BASE_BACKOFF_S * (2**attempt) * (0.5 + random.random()))  # noqa: S311

    @staticmethod
    def _raise_for_status(response: Any, operation: str) -> None:
        """4xx/5xx onto our declared errors. Separate types, not one error with a
        status code, because the graph acts on each differently."""
        status = response.status_code
        if status < 400:
            return
        detail = response.text[:400]
        if status == 429:
            raise QuotaExhausted(f"{operation}: 429 monthly limit reached — {detail}")
        if status == 409:
            raise SuperDocsConflict(f"{operation}: 409 document in use — {detail}")
        if status < 500:
            raise SuperDocsRejected(f"{operation}: HTTP {status} — our request is wrong: {detail}")
        raise SuperDocsUnavailable(f"{operation}: HTTP {status} — {detail}")

    @staticmethod
    def _json(response: Any, operation: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise MalformedResponse(f"{operation}: response was not JSON") from exc
        if not isinstance(body, dict):
            raise MalformedResponse(f"{operation}: expected an object, got {type(body).__name__}")
        return body

    # ── documents ─────────────────────────────────────────────────────────
    def upload_document(
        self,
        *,
        session_id: str,
        filename: str,
        data: bytes,
        open_mode: str = "replace",
    ) -> UploadResult:
        """Upload, then resolve the durable id. Two free calls: `POST
        /v1/documents/upload`, then `GET /v1/sessions/{id}/documents` for
        `durable_document_id`. The second is not optional — see `UploadResult`."""
        response = self._request(
            "POST",
            "/v1/documents/upload",
            operation="upload_document",
            files={"file": (filename, data, _content_type(filename))},
            data={"session_id": session_id, "open_mode": open_mode},
        )
        upload_body = self._json(response, "upload_document")
        listing = self._request(
            "GET", f"/v1/sessions/{session_id}/documents", operation="list_session_documents"
        )
        return parse_upload(upload_body, self._json(listing, "list_session_documents"))

    def list_session_documents(self, *, session_id: str) -> list[dict[str, Any]]:
        """The only source of `durable_document_id`. Free."""
        response = self._request(
            "GET", f"/v1/sessions/{session_id}/documents", operation="list_session_documents"
        )
        return list(self._json(response, "list_session_documents").get("documents", []))

    def open_documents(self, *, session_id: str, document_ids: list[str]) -> list[str]:
        """`POST /v1/sessions/{id}/documents/open`. Free.

        **The multi-document creation primitive**, and it took reading the
        published spec to find it. Probing had suggested a session was
        single-document — `POST /v1/sessions/{id}/documents` is 405, GET-only —
        and the conclusion drawn from that was wrong. `GET /openapi.json` on the
        live API lists 77 routes including `documents/blank`, `documents/open`
        and `documents/{id}/focus`. Measured 2026-08-16.

        Takes **durable** ids and returns the ones it opened. The documents are
        shared into the session, never copied, so opening a part does not
        duplicate it.
        """
        response = self._request(
            "POST",
            f"/v1/sessions/{session_id}/documents/open",
            operation="open_documents",
            json={"document_ids": document_ids},
        )
        return [str(item) for item in self._json(response, "open_documents").get("opened", [])]

    def whoami(self) -> Quota:
        """Free. The only endpoint that reports quota — checked before a run."""
        response = self._request("GET", "/v1/agents/whoami", operation="whoami")
        return parse_quota(self._json(response, "whoami"))

    # ── chat ──────────────────────────────────────────────────────────────
    def chat_async(
        self,
        *,
        session_id: str,
        message: str,
        approval_mode: str = "ask_every_time",
        response_mode: str = "compact",
        idempotency_marker: str,
    ) -> JobHandle:
        """Start an edit. `idempotency_marker` is embedded in the message so a
        replay after a crash is recognised via `get_session_jobs`, not launched
        twice. `retry_safe=False`: this spends an op and mutates a document, so a
        timeout raises `SuperDocsAmbiguous` and recovery is the marker, never a
        second launch."""
        payload = {
            "session_id": session_id,
            "message": f"{message}\n\n{marker_token(idempotency_marker)}",
            "approval_mode": approval_mode,
            "response_mode": response_mode,
        }
        response = self._request(
            "POST", "/v1/chat/async", operation="chat_async", retry_safe=False, json=payload
        )
        body = self._json(response, "chat_async")
        job_id = body.get("job_id") or body.get("id")
        if not job_id:
            raise MalformedResponse(f"chat_async: no job_id in response (keys: {sorted(body)})")
        self._record_usage("chat_async", body)
        return JobHandle(
            job_id=str(job_id), session_id=session_id, status=str(body.get("status", "pending"))
        )

    def get_job(self, job_id: str) -> Job:
        response = self._request("GET", f"/v1/jobs/{job_id}", operation="get_job")
        return parse_job(self._json(response, "get_job"))

    def get_session_jobs(self, session_id: str) -> list[Job]:
        """Crash recovery reads this. If a job carrying our marker exists, the
        call went through and we adopt it instead of re-sending."""
        response = self._request(
            "GET", f"/v1/sessions/{session_id}/jobs", operation="get_session_jobs"
        )
        body = self._json(response, "get_session_jobs")
        return [parse_job(j) for j in body.get("jobs", []) if isinstance(j, dict)]

    def find_job_by_marker(self, *, session_id: str, idempotency_marker: str) -> Job | None:
        """The other half of "never relaunch blind": after an ambiguous
        `chat_async`, did the turn actually start? Matched on the embedded marker,
        not timing — a session holds several jobs. Matched as a closed token
        (`[doctask-run: run-1]`, brackets included), because a substring search
        finds `run-1` inside `run-12` and sequential ids collide. Searched in the
        echoed message fields, not the whole metadata blob."""
        token = marker_token(idempotency_marker)
        for job in self.get_session_jobs(session_id):
            for key in ("message", "request_message"):
                value = job.metadata.get(key)
                if isinstance(value, str) and token in value:
                    return job
        return None

    def wait_for_job(
        self,
        job_id: str,
        *,
        poll_interval_s: float = 2.0,
        max_wait_s: float = MAX_JOB_WAIT_S,
        until: frozenset[str] | None = None,
    ) -> Job:
        """Poll until the job reaches a state worth acting on. Stops on
        `awaiting_approval` too — the turn is waiting on a human, and polling
        further just burns requests. Here, not in the graph, because T2.1 and
        T2.2 wait for jobs too and have no graph."""
        stop_at = until if until is not None else TERMINAL_JOB_STATES | {"awaiting_approval"}
        deadline = self._now() + max_wait_s

        while True:
            job = self.get_job(job_id)
            if job.status in stop_at:
                return job
            if self._now() >= deadline:
                # Not an invented error — the job may still be running. The caller
                # parks; it does not mark the job failed.
                raise SuperDocsAmbiguous(
                    f"job {job_id} still {job.status!r} after {max_wait_s:.0f}s — "
                    "not abandoned, not finished. Park and re-poll."
                )
            self._sleep(poll_interval_s)

    # ── approvals ─────────────────────────────────────────────────────────
    def approve(
        self, *, session_id: str, job_id: str, changes: list[ChangeDecision]
    ) -> ApproveResult:
        """`POST /v1/chat/{session_id}/approve` with
        `{job_id, approved, changes:[{change_id, approved, feedback?}]}`.

        `job_id` is required — an approval is scoped to the turn that proposed the
        changes, not the session. `approved` at the top level is `any(...)`, not
        `True`: hard-coding True while sending all-False decisions would be a
        mixed message about the one thing that must never be ambiguous.
        """
        decisions = [
            {"change_id": c.change_id, "approved": c.approved}
            | ({"feedback": c.feedback} if c.feedback else {})
            for c in changes
        ]
        payload = {
            "job_id": job_id,
            "approved": any(c.approved for c in changes),
            "changes": decisions,
        }
        response = self._request(
            "POST", f"/v1/chat/{session_id}/approve", operation="approve", json=payload
        )
        return parse_approve_result(self._json(response, "approve"))

    def re_edit(self, *, session_id: str, chunk_id: str, mode: str = "merge") -> None:
        """`POST /v1/sessions/{sid}/chunks/{cid}/re-edit`. Billable.

        The one method here with no recording behind it: the probe never called
        this route (it costs an op), so the request shape is pinned by a test and
        the response is not asserted at all — inventing one is the mistake the
        recorded fixtures exist to prevent. `retry_safe=False` because it mutates
        a chunk. No graph node calls it yet; a future flow must probe and record
        the response before relying on it.
        """
        self._request(
            "POST",
            f"/v1/sessions/{session_id}/chunks/{chunk_id}/re-edit",
            operation="re_edit",
            retry_safe=False,
            json={"mode": mode},
        )

    # ── reads and export ──────────────────────────────────────────────────
    def structure(self, *, durable_document_id: str) -> Structure:
        """`GET /v1/documents/{durable_id}`. Free. Keyed by the DURABLE id, not a
        session — there is no session-scoped `/structure` endpoint. The only
        SuperDocs call the API process makes, via `asyncio.to_thread`."""
        response = self._request(
            "GET", f"/v1/documents/{durable_document_id}", operation="structure"
        )
        return parse_structure(self._json(response, "structure"))

    def document_html(self, *, durable_document_id: str) -> str:
        """`?include_html=true`. Blocks carry `data-chunk-id`, and out-of-flow
        parts additionally carry `data-part-type`."""
        response = self._request(
            "GET",
            f"/v1/documents/{durable_document_id}",
            operation="document_html",
            params={"include_html": "true"},
        )
        return str(self._json(response, "document_html").get("html") or "")

    def export(
        self,
        *,
        fmt: str = "docx",
        session_id: str | None = None,
        html: str | None = None,
        filename: str | None = None,
    ) -> ExportResult:
        """Export a session, or a raw HTML fragment.

        Passing `html` instead of `session_id` is what makes T2.2 possible:
        splitting is stateless HTML slicing plus one export per part, with no
        extra sessions and no mutation of the master document.
        """
        if bool(session_id) == bool(html):
            raise SuperDocsRejected("export: pass exactly one of session_id or html")

        payload: dict[str, Any] = {"format": fmt}
        if session_id:
            payload["session_id"] = session_id
        if html:
            payload["html"] = html
        if filename:
            payload["filename"] = filename

        response = self._request(
            "POST", "/v1/documents/export", operation="export", retry_safe=False, json=payload
        )
        headers = response.headers
        return ExportResult(
            content=response.content,
            filename=filename or _filename_from(headers) or f"export.{fmt}",
            content_type=headers.get("content-type", "application/octet-stream"),
            warnings=decode_export_warnings(headers.get("X-Export-Warnings")),
        )

    # ── telemetry ─────────────────────────────────────────────────────────
    def _record_usage(self, operation: str, body: dict[str, Any]) -> None:
        """Only when the response actually carries usage. No recorded response
        body does, so this stays silent rather than handing the callback zeros a
        cost report would present as "this call was free"."""
        if self._on_usage is None:
            return
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return
        self._on_usage(
            UsageRecord(
                operation=operation,
                ops_charged=int(usage.get("ops_charged") or 0),
                ops_remaining=usage.get("ops_remaining"),
                ops_limit=usage.get("ops_limit"),
                model_tier=str(usage.get("model_tier") or self.model_tier),
            )
        )


MARKER_PREFIX = "[doctask-run: "
MARKER_SUFFIX = "]"
"""Embedded in the message so a crash replay can find its own turn. Appended to
our instruction, not sent as a field, because the API has no idempotency header —
`get_session_jobs` echoes the message, so the marker is what survives a crash.
Closed on both sides: without the suffix, `run-1` matches `run-12`, and with
sequential ids a crashed run would adopt another's job and approve changes it
never proposed."""


def marker_token(marker: str) -> str:
    """The complete, delimited token — emitted and searched for as one unit."""
    return f"{MARKER_PREFIX}{marker}{MARKER_SUFFIX}"


def _ambiguous(where: str, cause: str) -> str:
    return (
        f"{where}: {cause} after the request was sent — cannot tell whether it "
        "started. Not retried; adopt the existing job or park."
    )


def _content_type(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith((".md", ".markdown")):
        return "text/markdown"
    return "text/plain" if lowered.endswith(".txt") else "application/octet-stream"


def _filename_from(headers: Any) -> str | None:
    disposition = headers.get("content-disposition", "")
    if "filename=" not in disposition:
        return None
    return disposition.split("filename=", 1)[1].strip().strip('"') or None
