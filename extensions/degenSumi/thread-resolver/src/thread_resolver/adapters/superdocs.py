"""The SuperDocs REST API behind the editing seam.

Four calls carry the work: upload a document, request an edit, decide on what
was proposed, export the result. Edits are requested asynchronously with review
required, so the service holds each change until a decision arrives.

Two details of the wire format are handled here rather than left to callers.
Proposed-change content can arrive as a JSON-encoded string inside an already
decoded object, so values are parsed a second time where that is what they are.
And an edit can take minutes to come back with no intermediate signal, so the
job is polled to a deadline rather than waited on in one request.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import Mapping
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from thread_resolver.config import Settings
from thread_resolver.domain.models import DocumentPayload, ProposedEdit
from thread_resolver.ports.editor import (
    EditingError,
    EditingService,
    EditingUnavailable,
    EditSession,
    Proposal,
    Usage,
)

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "canceled", "error"})
APPROVAL_STATUSES = frozenset({"awaiting_approval", "pending_approval", "awaiting_review"})

_TRANSIENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)


class SuperDocsEditingService(EditingService):
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.superdocs_base_url,
            headers={"Authorization": f"Bearer {settings.require_superdocs_key()}"},
            timeout=settings.request_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- port ---------------------------------------------------------------

    async def open_document(self, payload: DocumentPayload) -> EditSession:
        session_id = f"tr-{abs(hash(payload.filename)) % 10**10}-{int(time.time())}"
        body = await self._post(
            "/v1/documents/upload-base64",
            {
                "filename": payload.filename,
                "file_base64": base64.b64encode(payload.data).decode(),
                "session_id": session_id,
            },
        )
        return EditSession(
            session_id=body.get("session_id", session_id),
            document_name=body.get("filename", payload.filename),
        )

    async def propose_edit(self, session: EditSession, instruction: str) -> Proposal:
        """Ask for a change and wait until it is held for approval.

        The document is not sent again: the session already holds it, and
        resending it on every request would be paid for in latency for no gain.
        """
        started = await self._post(
            "/v1/chat/async",
            {
                "message": instruction,
                "session_id": session.session_id,
                "async_mode": True,
                "approval_mode": "ask_every_time",
            },
        )
        job_id = started.get("job_id")
        if not job_id:
            raise EditingError(f"the edit request returned no job id: {_clip(started)}")

        job = await self._await_job(job_id)
        return Proposal(
            job_id=job_id,
            session_id=session.session_id,
            edits=_read_changes(job),
        )

    async def decide(self, proposal: Proposal, decisions: Mapping[str, bool]) -> None:
        if not proposal.edits:
            return

        undecided = {edit.change_id for edit in proposal.edits} - set(decisions)
        if undecided:
            raise EditingError(f"no decision was given for {sorted(undecided)}")

        any_approved = any(decisions[edit.change_id] for edit in proposal.edits)
        await self._post(
            f"/v1/chat/{proposal.session_id}/approve",
            {
                "job_id": proposal.job_id,
                # Required even when every change carries its own decision.
                "approved": any_approved,
                "changes": [
                    {"change_id": edit.change_id, "approved": bool(decisions[edit.change_id])}
                    for edit in proposal.edits
                ],
            },
        )

    async def export(self, session: EditSession, file_format: str = "docx") -> DocumentPayload:
        response = await self._request(
            "POST",
            "/v1/documents/export",
            json={
                "session_id": session.session_id,
                "format": file_format,
                "source_filename": session.document_name,
            },
        )
        return DocumentPayload(filename=session.document_name, data=response.content)

    async def usage(self) -> Usage | None:
        try:
            body = await self._get("/v1/agents/whoami")
        except EditingError:
            return None
        quota = body.get("quota") or {}
        if not quota:
            return None
        return Usage(
            used=int(quota.get("used", 0)),
            limit=int(quota.get("monthly_limit", 0)),
            remaining=int(quota.get("remaining", 0)),
        )

    # -- job polling --------------------------------------------------------

    async def _await_job(self, job_id: str) -> dict[str, Any]:
        """Poll until the job holds changes, finishes, or the deadline passes.

        A long silence is the documented behaviour for large documents, so a
        slow job is waited on rather than treated as a failure.
        """
        deadline = time.monotonic() + self._settings.job_timeout_seconds

        while True:
            job = await self._get(f"/v1/jobs/{job_id}")
            status = str(job.get("status", "")).lower()

            if status in APPROVAL_STATUSES:
                return job
            if status in TERMINAL_STATUSES:
                if status != "completed":
                    raise EditingError(
                        f"the edit job ended as {status}: {_clip(job.get('error') or job)}"
                    )
                return job

            if time.monotonic() > deadline:
                raise EditingUnavailable(
                    f"the edit job was still {status or 'pending'} after "
                    f"{self._settings.job_timeout_seconds:.0f}s. It may still finish; "
                    f"resume this run to pick it up."
                )
            await asyncio.sleep(self._settings.job_poll_seconds)

    # -- transport ----------------------------------------------------------

    async def _get(self, path: str) -> dict[str, Any]:
        return _as_object(await self._request("GET", path))

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return _as_object(await self._request("POST", path, json=body))

    @retry(
        retry=retry_if_exception_type(_TRANSIENT),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except _TRANSIENT as error:
            raise EditingUnavailable(f"{method} {path} did not complete: {error}") from error

        if response.status_code >= 500:
            raise EditingUnavailable(
                f"{method} {path} returned {response.status_code}. The service is "
                f"unavailable; the document was not changed."
            )
        if response.status_code == 429:
            raise EditingUnavailable(
                f"{method} {path} was rate limited. Reduce --concurrency and try again."
            )
        if response.status_code >= 400:
            raise EditingError(
                f"{method} {path} returned {response.status_code}: {_clip(response.text)}"
            )
        return response


# -- decoding ---------------------------------------------------------------


def _as_object(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as error:
        raise EditingError(f"the response was not JSON: {_clip(response.text)}") from error
    if not isinstance(body, dict):
        raise EditingError(f"expected an object, got {type(body).__name__}")
    return body


def _reparse(value: Any) -> Any:
    """Decode a value that is itself a JSON document carried as a string.

    Proposed-change content arrives this way. Leaving it as a string is the
    common cause of a diff whose every field reads as undefined.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except ValueError:
        return value


def _read_changes(job: dict[str, Any]) -> tuple[ProposedEdit, ...]:
    """Pull proposed changes out of a job, wherever the payload carries them."""
    raw = _find_pending_changes(job)
    if not isinstance(raw, list):
        return ()

    edits = []
    for entry in raw:
        change = _reparse(entry)
        if not isinstance(change, dict):
            continue
        change_id = str(change.get("change_id") or change.get("id") or "")
        if not change_id:
            continue
        edits.append(
            ProposedEdit(
                change_id=change_id,
                chunk_id=_text(change.get("chunk_id")) or None,
                operation=_text(change.get("operation")) or "edit",
                old_html=_text(change.get("old_html")),
                new_html=_text(change.get("new_html")),
                explanation=_text(change.get("ai_explanation") or change.get("explanation")),
            )
        )
    return tuple(edits)


def _find_pending_changes(job: dict[str, Any]) -> Any:
    """Look for the change list in each place a job may carry it.

    The list is documented under `metadata`, and the top level and `result` are
    checked as well so that a payload shaped differently is read rather than
    silently treated as an empty proposal.
    """
    for container in (_reparse(job.get("metadata")), job, _reparse(job.get("result"))):
        if isinstance(container, dict):
            found = _reparse(container.get("pending_changes"))
            if isinstance(found, list):
                return found
    return []


def _text(value: Any) -> str:
    parsed = _reparse(value)
    if parsed is None:
        return ""
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, dict):
        for key in ("html", "content", "text", "value"):
            if key in parsed:
                return _text(parsed[key])
    return str(parsed)


def _clip(value: Any, limit: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text[:limit] + ("..." if len(text) > limit else "")
