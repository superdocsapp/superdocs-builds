"""
@file: backend/services/superdocs_client.py
@description: Async client for the SuperDocs v1 REST API. Wraps upload, chat (sync and
    async), the human-in-the-loop approval cycle, job polling, and export. Written
    against the published API rather than a document-scoped guess: SuperDocs is
    session-centric, approvals are scoped to (session_id, job_id), and export is a POST
    that returns raw bytes.
@flow: SuperDocsClient(api_key) -> upload_document() loads a file into a session ->
    send_edit() starts an async chat job and polls until it either completes or pauses
    -> if it paused for review, caller inspects proposed changes and calls
    approve_changes() -> poll resumes -> export_document() returns the finished bytes.
    Every HTTP call funnels through _request(), which owns retry, backoff, and the
    error taxonomy.
@dependencies:
    - httpx: async HTTP with per-request timeout control
    - backend.config.settings: base URL, key, poll budget, model tier
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Terminal job states. Anything else means "keep polling".
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

# Status codes worth retrying. 429 is included but handled specially so we can honour
# Retry-After rather than guessing. 409 is deliberately absent: a conflict means we
# called the wrong endpoint for the pause type, and retrying repeats the mistake.
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class SuperDocsError(RuntimeError):
    """Base class for every SuperDocs failure surfaced to a node."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.retryable = retryable


class SuperDocsAuthError(SuperDocsError):
    """401/403. Never retryable — the key is wrong, revoked, or not permitted here."""


class SuperDocsQuotaError(SuperDocsError):
    """429 from the application layer: the monthly operation quota is exhausted.

    Distinct from an infrastructure 429 (plain-text, no Retry-After), which the docs
    describe as a transient surge response and which we do retry.
    """

    def __init__(self, message: str, *, retry_after_s: int | None = None, **kw: Any):
        super().__init__(message, **kw)
        self.retry_after_s = retry_after_s


class SuperDocsTimeout(SuperDocsError):
    """We stopped waiting. The operation may still be running server-side.

    Deliberately not a crash: the caller is expected to surface this as a pause with a
    job_id it can resume polling later, not to discard the run.
    """

    def __init__(self, message: str, *, job_id: str | None = None, **kw: Any):
        super().__init__(message, **kw)
        self.job_id = job_id


class SuperDocsSessionBusy(SuperDocsError):
    """409 session_busy: a job is still active in this session.

    Distinct from the other 409 (wrong resume endpoint) because this one is recoverable —
    the active job can be cancelled, or the work moved to a fresh session. Conflating them
    meant a run that had failed mid-edit could never be retried: its own abandoned job
    blocked every subsequent attempt in the same session.
    """

    def __init__(self, message: str, *, active_jobs: int = 0, **kw):
        super().__init__(message, **kw)
        self.active_jobs = active_jobs


class SuperDocsPayloadTooLarge(SuperDocsError):
    """413. Body or export exceeded a cap. Carries the structured detail when present."""


@dataclass(slots=True)
class ProposedChange:
    """One AI-proposed edit awaiting a human decision.

    Field names mirror the API exactly so a reviewer can diff this against the docs.
    `document_id` is populated in multi-document sessions and is what lets the approval
    UI group a batch per document.
    """

    change_id: str
    operation: Literal["edit", "create", "delete"]
    chunk_id: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str
    insert_after_chunk_id: str | None = None
    document_id: str | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "ProposedChange":
        return cls(
            change_id=raw["change_id"],
            operation=raw.get("operation", "edit"),
            chunk_id=raw.get("chunk_id"),
            old_html=raw.get("old_html"),
            new_html=raw.get("new_html"),
            ai_explanation=raw.get("ai_explanation") or "",
            insert_after_chunk_id=raw.get("insert_after_chunk_id"),
            document_id=raw.get("document_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "operation": self.operation,
            "chunk_id": self.chunk_id,
            "old_html": self.old_html,
            "new_html": self.new_html,
            "ai_explanation": self.ai_explanation,
            "insert_after_chunk_id": self.insert_after_chunk_id,
            "document_id": self.document_id,
        }


@dataclass(slots=True)
class EditResult:
    """Outcome of one edit instruction.

    Exactly one of these is true:
      - awaiting_approval: changes are pending a human decision (`pending_changes`)
      - awaiting_continue:  a large edit paused and needs /continue, not /approve
      - completed:          the turn finished; `updated_html` may be populated
    """

    job_id: str
    session_id: str
    status: str
    awaiting_kind: str | None = None
    pending_changes: list[ProposedChange] = field(default_factory=list)
    continue_prompt: dict[str, Any] | None = None
    response_text: str = ""
    updated_html: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def awaiting_approval(self) -> bool:
        return self.status == "awaiting_approval" and self.awaiting_kind != "continue_prompt"

    @property
    def awaiting_continue(self) -> bool:
        return self.status == "awaiting_approval" and self.awaiting_kind == "continue_prompt"

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def ops_charged(self) -> int:
        return int(self.usage.get("ops_charged", 0) or 0)


class SuperDocsClient:
    """Async SuperDocs client.

    Usage:
        async with SuperDocsClient() as client:
            await client.upload_document("digest.docx", session_id="run-123")
            result = await client.send_edit("run-123", "Fill in the summary")
            if result.awaiting_approval:
                await client.approve_changes("run-123", result.job_id, approved_ids=[...])
            data = await client.export_document("run-123", fmt="docx")
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # Resolve the key lazily via require_* so importing this module never fails.
        self._api_key = api_key or settings.require_superdocs_key()
        self._base_url = (base_url or settings.superdocs_base_url).rstrip("/")
        self._external_client = client is not None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.superdocs_connect_timeout_s,
                read=settings.superdocs_connect_timeout_s,
            )
        )

    async def __aenter__(self) -> "SuperDocsClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if not self._external_client:
            await self._client.aclose()

    # ---- internals -------------------------------------------------------

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    @staticmethod
    def _redact(text: str) -> str:
        """Strip anything key-shaped out of text bound for a log or an exception.

        The key must never appear in logs, even partially — so we replace the whole
        token rather than masking a suffix.
        """
        import re

        return re.sub(r"\b(sk|lce|gsk)_[A-Za-z0-9_\-]+", "<redacted-key>", text)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        expect_binary: bool = False,
        max_attempts: int | None = None,
    ) -> Any:
        """Single funnel for every HTTP call: retry, backoff, and error classification.

        Retries only on the statuses the docs describe as transient, plus connection
        errors. Auth and validation failures fail fast — retrying a 401 just burns time.
        """
        url = f"{self._base_url}{path}"
        attempts = max_attempts or settings.node_max_retries
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    headers=self._auth_headers,
                    json=json_body,
                    files=files,
                    data=data,
                    params=params,
                    timeout=timeout_s or settings.superdocs_connect_timeout_s,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise SuperDocsError(
                        f"Network failure calling {method} {path} after {attempt} attempts: {exc}",
                        retryable=True,
                    ) from exc
                await self._sleep_backoff(attempt)
                continue

            if response.status_code < 400:
                if expect_binary:
                    return response.content
                if not response.content:
                    return {}
                try:
                    return response.json()
                except ValueError:
                    return {"raw_text": response.text}

            handled = self._classify_error(response, method, path)
            if handled.retryable and attempt < attempts:
                last_error = handled
                await self._sleep_backoff(
                    attempt,
                    override_s=getattr(handled, "retry_after_s", None),
                )
                continue
            raise handled

        raise SuperDocsError(
            f"Exhausted retries for {method} {path}: {last_error}", retryable=True
        )

    def _classify_error(
        self, response: httpx.Response, method: str, path: str
    ) -> SuperDocsError:
        """Turn an HTTP error response into the right exception type.

        The 429 split matters: the docs distinguish an application 429 (JSON body plus
        Retry-After — quota exhausted, retrying is pointless within the window) from an
        infrastructure 429 (plain text, no Retry-After — a surge, retry with jitter).
        """
        status = response.status_code
        body_text = self._redact(response.text[:2000])
        try:
            payload = response.json()
        except ValueError:
            payload = None

        detail = ""
        if isinstance(payload, dict):
            raw_detail = payload.get("detail")
            detail = (
                raw_detail
                if isinstance(raw_detail, str)
                else str(raw_detail) if raw_detail is not None else ""
            )
        detail = self._redact(detail) or body_text

        if status in (401, 403):
            return SuperDocsAuthError(
                f"SuperDocs rejected credentials on {method} {path}: {detail}",
                status_code=status,
                payload=payload,
            )

        if status == 413:
            return SuperDocsPayloadTooLarge(
                f"Payload too large on {method} {path}: {detail}",
                status_code=status,
                payload=payload,
            )

        if status == 429:
            retry_after_raw = response.headers.get("Retry-After")
            is_application_429 = payload is not None
            if is_application_429:
                retry_after = int(retry_after_raw) if retry_after_raw else None
                return SuperDocsQuotaError(
                    f"SuperDocs quota exhausted on {method} {path}: {detail}",
                    status_code=status,
                    payload=payload,
                    retry_after_s=retry_after,
                    retryable=False,
                )
            # Plain-text 429 == infrastructure surge. Back off and retry.
            return SuperDocsError(
                f"SuperDocs throttled {method} {path} (surge): {body_text}",
                status_code=status,
                retryable=True,
            )

        if status == 409:
            # error_code may be top level or nested under "detail" depending on which
            # layer produced the error. Checking only the top level meant session_busy
            # went unrecognised and was reported as a wrong-endpoint conflict.
            error_code = ""
            nested: dict[str, Any] = {}
            if isinstance(payload, dict):
                raw = payload.get("detail")
                if isinstance(raw, dict):
                    nested = raw
                error_code = str(
                    payload.get("error_code") or nested.get("error_code") or ""
                )

            if error_code == "session_busy":
                # A previous job in this session never finished. Recoverable: cancel it.
                active = 0
                for source in (payload if isinstance(payload, dict) else {}, nested):
                    try:
                        value = source.get("active_jobs")
                    except AttributeError:
                        continue
                    if value is not None:
                        try:
                            active = int(value)
                            break
                        except (TypeError, ValueError):
                            pass
                return SuperDocsSessionBusy(
                    f"Session already has {active or 'an'} active job. The previous "
                    f"attempt in this session did not finish: {detail}",
                    active_jobs=active,
                    status_code=status,
                    payload=payload,
                    retryable=False,
                )

            # Otherwise: most likely /approve called on a continue-prompt pause, or the
            # reverse. Retrying repeats the same mistake, so fail loudly.
            return SuperDocsError(
                f"Conflict on {method} {path} — likely the wrong resume endpoint for "
                f"this pause type (check metadata.awaiting_kind): {detail}",
                status_code=status,
                payload=payload,
                retryable=False,
            )

        return SuperDocsError(
            f"SuperDocs {status} on {method} {path}: {detail}",
            status_code=status,
            payload=payload,
            retryable=status in _RETRYABLE_STATUSES,
        )

    @staticmethod
    async def _sleep_backoff(attempt: int, override_s: float | None = None) -> None:
        """Exponential backoff with jitter, capped. Honours Retry-After when given."""
        if override_s is not None:
            await asyncio.sleep(min(float(override_s), 60.0))
            return
        delay = min(settings.node_retry_base_delay_s * (2 ** (attempt - 1)), 30.0)
        await asyncio.sleep(delay + random.uniform(0, delay * 0.25))

    # ---- public API ------------------------------------------------------

    async def verify_key(self) -> bool:
        """Confirm the API key works.

        Uses GET /v1/sessions deliberately: it consumes no operations and accepts sk_
        keys. /v1/users/me looks like the natural choice but rejects API keys with a
        401, which makes a perfectly good key look broken.
        """
        try:
            await self._request("GET", "/v1/sessions", max_attempts=1)
            return True
        except SuperDocsAuthError:
            return False

    async def upload_document(
        self,
        file_path: str | Path,
        session_id: str,
        *,
        open_mode: Literal["replace", "new_focused", "background"] = "replace",
    ) -> dict[str, Any]:
        """Load a file into a session as the active editable document.

        Streams from disk rather than reading the whole file into memory, so a large
        template never sits in the process heap. Returns the API payload including the
        parsed HTML, chunk count, and version id.
        """
        path = Path(file_path)
        if not path.is_file():
            raise SuperDocsError(f"Upload source not found: {path}")

        with path.open("rb") as fh:
            payload = await self._request(
                "POST",
                "/v1/documents/upload",
                files={"file": (path.name, fh, "application/octet-stream")},
                data={"session_id": session_id, "open_mode": open_mode},
                timeout_s=180.0,
            )
        logger.info(
            "Uploaded %s into session %s (%s chunks)",
            path.name,
            session_id,
            payload.get("chunks_count"),
        )
        return payload

    async def upload_attachment(
        self, file_path: str | Path, session_id: str
    ) -> dict[str, Any]:
        """Attach a read-only reference file the AI can search while editing.

        Used for last quarter's digest: we want the AI able to cite it, but we never
        want it to become the editable document.
        """
        path = Path(file_path)
        if not path.is_file():
            raise SuperDocsError(f"Attachment source not found: {path}")
        with path.open("rb") as fh:
            return await self._request(
                "POST",
                "/v1/attachments/upload",
                files={"file": (path.name, fh, "application/octet-stream")},
                data={"session_id": session_id},
                timeout_s=180.0,
            )

    async def send_edit(
        self,
        session_id: str,
        instruction: str,
        *,
        document_html: str | None = None,
        require_approval: bool = True,
        document_id: str | None = None,
        poll: bool = True,
    ) -> EditResult:
        """Send one edit instruction and (by default) poll until it settles.

        Uses the async endpoint so long edits don't block on a single HTTP call and so
        human-in-the-loop review is available. Returns as soon as the job reaches a
        terminal state *or* pauses — a pause is a normal outcome here, not an error.
        """
        body: dict[str, Any] = {
            "message": instruction,
            "session_id": session_id,
            "approval_mode": "ask_every_time" if require_approval else "approve_all",
            "model_tier": settings.superdocs_model_tier,
            "thinking_depth": settings.superdocs_thinking_depth,
        }
        # Only send document_html to load or replace a document. On follow-up turns the
        # server already holds it, and re-sending wastes tokens.
        if document_html is not None:
            body["document_html"] = document_html
        if document_id is not None:
            body["document_id"] = document_id

        started = await self._request("POST", "/v1/chat/async", json_body=body)
        job_id = started.get("job_id")
        if not job_id:
            raise SuperDocsError(
                f"chat/async did not return a job_id: {started}", payload=started
            )

        if not poll:
            return EditResult(job_id=job_id, session_id=session_id, status="pending")

        return await self.poll_until_settled(job_id, session_id)

    async def poll_until_settled(
        self, job_id: str, session_id: str, *, timeout_s: int | None = None
    ) -> EditResult:
        """Poll a job until it completes, fails, or pauses for human input.

        Exponential backoff between polls. A timeout raises SuperDocsTimeout carrying
        the job_id — the operation is very likely still running server-side, so the
        caller can resume polling rather than treating the run as dead.
        """
        budget = timeout_s or settings.superdocs_poll_timeout_s
        deadline = asyncio.get_event_loop().time() + budget
        delay = settings.superdocs_poll_initial_s

        while True:
            job = await self._request("GET", f"/v1/jobs/{job_id}")
            status = job.get("status", "unknown")
            metadata = job.get("metadata") or {}

            if status == "awaiting_approval":
                awaiting_kind = metadata.get("awaiting_kind")
                # Two distinct pauses share this status. Branching on awaiting_kind is
                # what keeps us from POSTing to the wrong endpoint and eating a 409.
                if awaiting_kind == "continue_prompt":
                    return EditResult(
                        job_id=job_id,
                        session_id=session_id,
                        status=status,
                        awaiting_kind=awaiting_kind,
                        continue_prompt=metadata.get("continue_prompt") or {},
                        raw=job,
                    )
                # Polling path: pending_changes is already a list of dicts. The extra
                # JSON parse the SSE path needs does NOT apply here and would throw.
                raw_changes = metadata.get("pending_changes") or []
                already_decided = metadata.get("pending_batch_decisions") or {}
                pending = [
                    ProposedChange.from_api(c)
                    for c in raw_changes
                    if c.get("change_id") not in already_decided
                ]
                return EditResult(
                    job_id=job_id,
                    session_id=session_id,
                    status=status,
                    awaiting_kind=awaiting_kind,
                    pending_changes=pending,
                    raw=job,
                )

            if status in _TERMINAL_STATUSES:
                if status == "failed":
                    raise SuperDocsError(
                        f"SuperDocs job {job_id} failed: {job.get('error')}",
                        payload=job,
                    )
                if status == "cancelled":
                    raise SuperDocsError(
                        f"SuperDocs job {job_id} was cancelled", payload=job
                    )
                result = job.get("result") or {}
                changes = result.get("document_changes") or {}
                return EditResult(
                    job_id=job_id,
                    session_id=session_id,
                    status=status,
                    response_text=result.get("response", ""),
                    updated_html=changes.get("updated_html"),
                    usage=result.get("usage") or {},
                    raw=job,
                )

            if asyncio.get_event_loop().time() > deadline:
                raise SuperDocsTimeout(
                    f"Job {job_id} still {status} after {budget}s. It is probably still "
                    f"running server-side — resume polling rather than restarting.",
                    job_id=job_id,
                )

            await asyncio.sleep(delay)
            delay = min(delay * 1.5, settings.superdocs_poll_max_s)

    async def approve_changes(
        self,
        session_id: str,
        job_id: str,
        *,
        approved_ids: list[str],
        rejected_ids: list[str] | None = None,
        feedback: dict[str, str] | None = None,
        poll: bool = True,
    ) -> EditResult:
        """Submit per-change approve/reject decisions, then resume polling.

        The `approved` field is required at the TOP LEVEL of the request even when every
        entry in `changes` carries its own decision. Omitting it returns a generic 422
        that reads like a schema bug rather than a missing field, so we always send it.
        """
        rejected_ids = rejected_ids or []
        feedback = feedback or {}

        changes: list[dict[str, Any]] = [
            {"change_id": cid, "approved": True} for cid in approved_ids
        ]
        for cid in rejected_ids:
            entry: dict[str, Any] = {"change_id": cid, "approved": False}
            if cid in feedback:
                entry["feedback"] = feedback[cid]
            changes.append(entry)

        if not changes:
            raise SuperDocsError("approve_changes called with no decisions")

        body = {
            "job_id": job_id,
            # Required at top level. Acts as the default for entries that omit their own
            # `approved`; ours always specify it, but the field is still mandatory.
            "approved": True,
            "changes": changes,
        }
        await self._request(
            "POST", f"/v1/chat/{session_id}/approve", json_body=body
        )
        logger.info(
            "Submitted %d approvals / %d rejections for job %s",
            len(approved_ids),
            len(rejected_ids),
            job_id,
        )
        if not poll:
            return EditResult(job_id=job_id, session_id=session_id, status="in_progress")
        return await self.poll_until_settled(job_id, session_id)

    async def continue_edit(
        self, session_id: str, job_id: str, *, proceed: bool = True
    ) -> EditResult:
        """Answer a large-edit continue prompt.

        Separate endpoint from /approve. Calling the wrong one for a given pause type
        returns 409, which is why poll_until_settled reports awaiting_kind.
        """
        await self._request(
            "POST",
            f"/v1/chat/{session_id}/continue",
            json_body={"job_id": job_id, "continue": proceed},
        )
        return await self.poll_until_settled(job_id, session_id)

    async def list_jobs(self, session_id: str) -> list[dict[str, Any]]:
        """Jobs belonging to a session, so an unfinished one can be found and cleared."""
        payload = await self._request(
            "GET", "/v1/jobs", params={"session_id": session_id}
        )
        if isinstance(payload, list):
            return payload
        return payload.get("jobs") or []

    async def wait_for_session_free(
        self, session_id: str, *, timeout_s: float = 180.0
    ) -> bool:
        """Block until the session has no unfinished job. Returns False on timeout.

        SuperDocs permits one active job per session. Approving a change set can leave
        follow-on work in flight that the original job id no longer reflects, so
        "poll_until_settled returned completed" does not imply "the session is free".
        Sending the next edit on that assumption produces 409 session_busy mid-run.
        """
        unfinished = {"pending", "in_progress", "awaiting_approval", "queued"}
        deadline = asyncio.get_event_loop().time() + timeout_s
        delay = 0.5
        while True:
            try:
                jobs = await self.list_jobs(session_id)
            except SuperDocsError as exc:
                # If we cannot see the jobs we cannot wait on them; let the caller try.
                logger.warning("Cannot list jobs for %s: %s", session_id, exc)
                return True

            active = [
                j for j in jobs
                if str(j.get("status", "")).lower() in unfinished
            ]
            if not active:
                return True

            if asyncio.get_event_loop().time() > deadline:
                logger.warning(
                    "Session %s still has %d active job(s) after %.0fs",
                    session_id, len(active), timeout_s,
                )
                return False

            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 5.0)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel one job. Returns False rather than raising if it cannot be cancelled."""
        try:
            await self._request("POST", f"/v1/jobs/{job_id}/cancel", max_attempts=1)
            return True
        except SuperDocsError as exc:
            logger.warning("Could not cancel job %s: %s", job_id, exc)
            return False

    async def clear_active_jobs(self, session_id: str) -> int:
        """Cancel every unfinished job in a session. Returns how many were cancelled.

        Called before starting work in a session that may carry an abandoned job from a
        previous failed attempt. Without this, a run that died mid-edit could never be
        retried — its own orphaned job blocked the session permanently.
        """
        unfinished = {"pending", "in_progress", "awaiting_approval", "queued"}
        cancelled = 0
        try:
            jobs = await self.list_jobs(session_id)
        except SuperDocsError as exc:
            logger.warning("Could not list jobs for session %s: %s", session_id, exc)
            return 0

        for job in jobs:
            if str(job.get("status", "")).lower() in unfinished:
                job_id = job.get("job_id") or job.get("id")
                if job_id and await self.cancel_job(str(job_id)):
                    cancelled += 1
                    logger.info("Cancelled stale job %s in session %s", job_id, session_id)
        return cancelled

    async def get_document_structure(self, document_id: str) -> dict[str, Any]:
        """Cheap, non-billable verification that an edit actually landed.

        The docs are explicit that this is the way to check structure — exporting a
        whole document just to confirm a heading exists is wasteful.
        """
        payload = await self._request("GET", f"/v1/documents/{document_id}")
        return payload.get("structure") or {}

    async def list_session_documents(self, session_id: str) -> list[dict[str, Any]]:
        """Roster of open documents in a session (metadata only — no HTML bodies)."""
        payload = await self._request(
            "GET", f"/v1/sessions/{session_id}/documents"
        )
        return payload.get("documents") or []

    async def export_document(
        self,
        session_id: str,
        *,
        fmt: Literal["docx", "pdf", "html", "markdown", "txt"] = "docx",
        filename: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> bytes:
        """Export the session's current document as bytes.

        POST, not GET, and the response body is the file itself rather than JSON.
        Non-fatal render issues arrive in the X-Export-Warnings header; we log them but
        do not fail the export, because a missing image should not block a digest.
        """
        body: dict[str, Any] = {"session_id": session_id, "format": fmt}
        opts = dict(options or {})
        if filename:
            opts["filename"] = filename
        if opts:
            body["options"] = opts

        content = await self._request(
            "POST",
            "/v1/documents/export",
            json_body=body,
            expect_binary=True,
            timeout_s=300.0,
        )
        if not isinstance(content, (bytes, bytearray)):
            raise SuperDocsError(f"Export returned non-binary payload: {type(content)}")
        logger.info("Exported session %s as %s (%d bytes)", session_id, fmt, len(content))
        return bytes(content)