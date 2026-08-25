"""SuperDocs REST client.

The audit found this module was imported by nothing but its own unit test: generation
just slept through a list of hardcoded stage names. `get_client()` is now the single
entry point used by the generation service, selected by `SUPERDOCS_MODE`.
"""

import asyncio
import base64
import hashlib
import json
import re
import time
import uuid
from typing import Any, Protocol

import httpx

REQUIRED_CHANGE_FIELDS = ("section", "before_value", "after_value")

# The four operations that make up the SuperDocs contract, in the order the close pack
# workflow exercises them. `send_edit_instruction` is the ledger's name for the
# `edit_document` adapter call; the rest match the adapter method names.
UPLOAD = "upload_document"
EDIT = "send_edit_instruction"
APPROVE = "approve_changes"
EXPORT = "export_document"
CONTRACT_OPERATIONS = (UPLOAD, EDIT, APPROVE, EXPORT)


class SuperDocsResponseError(RuntimeError):
    pass


class SuperDocsClientProtocol(Protocol):
    async def upload_document(self, filename: str, content: bytes) -> dict[str, Any]: ...

    async def edit_document(
        self, document_id: str, instruction: str, document_html: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def approve_changes(
        self, document_id: str, change_ids: list[str], rejected_change_ids: list[str] | None = None
    ) -> dict[str, Any]: ...

    async def export_document(
        self, document_id: str, approved_change_ids: list[str] | None = None
    ) -> dict[str, Any]: ...


class SuperDocsClient:
    """Live SuperDocs REST client (api.superdocs.app/v1).

    The public API is session-centric, not document-centric: a document is loaded into a
    session, edits are proposed by an async chat job, approvals are posted against that
    job, and the export is taken from the session. The close pack's four-operation
    contract is mapped onto it as follows:

    | Contract op       | Live call                                                     |
    | ----------------- | ------------------------------------------------------------- |
    | upload_document   | POST /documents/upload  (multipart file + session_id)          |
    | edit_document     | POST /chat/async (approval_mode=ask_every_time) + job polling  |
    | approve_changes   | POST /chat/{session_id}/approve                                |
    | export_document   | POST /documents/export  (binary body)                          |

    Because the caller only ever threads a single opaque `document_id` string, the
    session id is carried inside it (`"<session_id>::<slug>"`), and the job id is
    carried inside each `external_change_id` (`"<job_id>::<change_id>"`). That keeps the
    protocol and every existing call site unchanged.
    """

    # The edit job runs a real model over the whole document; probe runs took ~70s.
    EDIT_POLL_INTERVAL = 3.0
    EDIT_POLL_TIMEOUT = 300.0
    TRANSPORT_RETRIES = 3
    TRANSPORT_RETRY_BACKOFF = 1.5
    UPLOAD_TIMEOUT = 300.0
    ATTACHMENT_POLL_INTERVAL = 2.0
    ATTACHMENT_TIMEOUT = 240.0

    def __init__(self, api_key: str, base_url: str = "https://api.superdocs.app/v1") -> None:
        if not api_key:
            raise SuperDocsResponseError(
                "SUPERDOCS_MODE=live requires SUPERDOCS_API_KEY. Set it, or use SUPERDOCS_MODE=mock."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        # One session per client instance. Generation holds a single client across all
        # uploads plus the edit, so every source document lands in the same session.
        self._session_id = f"closepack-{uuid.uuid4().hex[:16]}"
        # Source files are attachments; the document being drafted is supplied by the
        # caller on the edit turn. Nothing about the working document is inferred here.

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _session_of(self, document_id: str) -> str:
        """Recover the session id from an opaque document id minted by `upload_document`."""
        return document_id.split("::", 1)[0] if "::" in document_id else document_id

    async def _request(self, method: str, path: str, timeout: float, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._send(method, path, timeout, **kwargs)
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise SuperDocsResponseError(
                f"SuperDocs returned {exc.response.status_code} for {method} {path}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SuperDocsResponseError(f"SuperDocs request failed for {method} {path}: {_describe(exc)}") from exc
        except ValueError as exc:
            raise SuperDocsResponseError(f"SuperDocs returned a non-JSON body for {method} {path}") from exc

    async def _send(self, method: str, path: str, timeout: float, **kwargs: Any) -> httpx.Response:
        """One request, retrying cheap transport faults.

        The gateway occasionally drops a multipart upload mid-flight
        (`RemoteProtocolError`). That fails in milliseconds and is worth retrying.

        A *timeout* is deliberately not retried. It costs the full timeout budget every
        attempt, so retrying a 300s upload three times would block generation for fifteen
        minutes and push the whole job past the server's own generation deadline. A
        timeout means the far side is genuinely struggling; report it and stop.
        """
        last: httpx.HTTPError | None = None
        for attempt in range(self.TRANSPORT_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(
                        method, f"{self.base_url}{path}", headers=self._headers, **kwargs
                    )
                    response.raise_for_status()
                    return response
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as exc:
                last = exc
                if attempt + 1 < self.TRANSPORT_RETRIES:
                    await asyncio.sleep(self.TRANSPORT_RETRY_BACKOFF * (attempt + 1))
        raise last  # type: ignore[misc]

    async def _request_bytes(self, method: str, path: str, timeout: float, **kwargs: Any) -> tuple[bytes, str]:
        """Like `_request`, for endpoints that return a file body rather than JSON."""
        try:
            response = await self._send(method, path, timeout, **kwargs)
            return response.content, response.headers.get("content-type", "")
        except httpx.HTTPStatusError as exc:
            raise SuperDocsResponseError(
                f"SuperDocs returned {exc.response.status_code} for {method} {path}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SuperDocsResponseError(f"SuperDocs request failed for {method} {path}: {_describe(exc)}") from exc

    async def upload_document(self, filename: str, content: bytes) -> dict[str, Any]:
        """Load one source document into the session as AI-queryable evidence.

        This posts to `/attachments/upload`, not `/documents/upload`. The two are easy to
        confuse and the difference is the whole integration: `/documents/upload` loads a
        file as *the active editable document*, so uploading eight source files simply
        replaced the editor's document eight times (every response came back with the
        same `document_id: "doc_primary"`). Nothing was retained as evidence, and the
        model answered the edit turn with "I couldn't detect any attached source
        documents in this session".

        Attachments are what the model can actually cite while editing.
        """
        payload = await self._request(
            "POST",
            "/attachments/upload",
            # SuperDocs extracts and indexes the file, so the wait scales with the
            # document, not the transfer. The seeded 1KB fixtures return in ~1.5s; a real
            # 2.7MB PDF exceeded a 120s budget and failed the whole run.
            timeout=self.UPLOAD_TIMEOUT,
            files={"file": (filename, content)},
            data={"session_id": self._session_id},
        )
        slug = filename.lower().replace(" ", "-")
        return {
            "document_id": f"{self._session_id}::{slug}",
            "session_id": self._session_id,
            "attachment_id": payload.get("attachment_id"),
            "processing_job_id": payload.get("job_id"),
            "filename": payload.get("filename", filename),
            "status": "uploaded",
            "bytes": len(content),
            "mode": "live",
        }

    async def _await_attachments(self, session_id: str) -> None:
        """Block until every uploaded source document has finished indexing.

        Attachments are processed asynchronously: the upload returns immediately with
        `status: "processing"` and a `job_id`, and the file is not queryable until that
        job finishes. Running the edit turn early is indistinguishable from having
        uploaded nothing at all - the model simply reports that it can see no source
        documents - so this gate is what makes the evidence real.

        The status payload is `{ready_attachments: [...], processing_jobs: [...],
        total_ready, total_processing}`. An earlier version of this looked for an
        `attachments` key, found nothing, read "no items" as "all finished" and returned
        instantly, which reintroduced the very race it exists to prevent.
        """
        deadline = time.monotonic() + self.ATTACHMENT_TIMEOUT
        while True:
            try:
                payload = await self._request("GET", f"/attachments/status/{session_id}", timeout=60)
            except SuperDocsResponseError:
                return  # Status is advisory; let the edit turn report any real problem.

            processing = payload.get("processing_jobs") or []

            failed = [job for job in processing if str(job.get("status", "")).lower() == "failed"]
            if failed:
                names = ", ".join(str(job.get("filename") or "a document") for job in failed)
                reason = next((job.get("error") for job in failed if job.get("error")), "no reason given")
                raise SuperDocsResponseError(
                    f"SuperDocs could not process {names}: {reason}"
                )

            still_running = [
                job for job in processing if str(job.get("status", "")).lower() not in ("completed", "ready", "failed")
            ]
            if not still_running:
                return

            if time.monotonic() >= deadline:
                slowest = ", ".join(
                    f"{job.get('filename')} ({job.get('progress', 0)}%)" for job in still_running
                )
                raise SuperDocsResponseError(
                    f"SuperDocs did not finish reading the source documents within "
                    f"{self.ATTACHMENT_TIMEOUT:.0f}s. Still processing: {slowest}"
                )
            await asyncio.sleep(self.ATTACHMENT_POLL_INTERVAL)

    async def edit_document(
        self, document_id: str, instruction: str, document_html: str | None = None
    ) -> list[dict[str, Any]]: ...

    async def approve_changes(
        self, document_id: str, change_ids: list[str], rejected_change_ids: list[str] | None = None
    ) -> dict[str, Any]: ...

    async def export_document(
        self, document_id: str, approved_change_ids: list[str] | None = None
    ) -> dict[str, Any]: ...


class SuperDocsClient:
    """Live SuperDocs REST client (api.superdocs.app/v1).

    The public API is session-centric, not document-centric: a document is loaded into a
    session, edits are proposed by an async chat job, approvals are posted against that
    job, and the export is taken from the session. The close pack's four-operation
    contract is mapped onto it as follows:

    | Contract op       | Live call                                                     |
    | ----------------- | ------------------------------------------------------------- |
    | upload_document   | POST /documents/upload  (multipart file + session_id)          |
    | edit_document     | POST /chat/async (approval_mode=ask_every_time) + job polling  |
    | approve_changes   | POST /chat/{session_id}/approve                                |
    | export_document   | POST /documents/export  (binary body)                          |

    Because the caller only ever threads a single opaque `document_id` string, the
    session id is carried inside it (`"<session_id>::<slug>"`), and the job id is
    carried inside each `external_change_id` (`"<job_id>::<change_id>"`). That keeps the
    protocol and every existing call site unchanged.
    """

    # The edit job runs a real model over the whole document; probe runs took ~70s.
    EDIT_POLL_INTERVAL = 3.0
    EDIT_POLL_TIMEOUT = 300.0
    TRANSPORT_RETRIES = 3
    TRANSPORT_RETRY_BACKOFF = 1.5
    UPLOAD_TIMEOUT = 300.0
    ATTACHMENT_POLL_INTERVAL = 2.0
    ATTACHMENT_TIMEOUT = 240.0

    def __init__(self, api_key: str, base_url: str = "https://api.superdocs.app/v1") -> None:
        if not api_key:
            raise SuperDocsResponseError(
                "SUPERDOCS_MODE=live requires SUPERDOCS_API_KEY. Set it, or use SUPERDOCS_MODE=mock."
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        # One session per client instance. Generation holds a single client across all
        # uploads plus the edit, so every source document lands in the same session.
        self._session_id = f"closepack-{uuid.uuid4().hex[:16]}"
        # Source files are attachments; the document being drafted is supplied by the
        # caller on the edit turn. Nothing about the working document is inferred here.

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _session_of(self, document_id: str) -> str:
        """Recover the session id from an opaque document id minted by `upload_document`."""
        return document_id.split("::", 1)[0] if "::" in document_id else document_id

    async def _request(self, method: str, path: str, timeout: float, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._send(method, path, timeout, **kwargs)
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise SuperDocsResponseError(
                f"SuperDocs returned {exc.response.status_code} for {method} {path}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SuperDocsResponseError(f"SuperDocs request failed for {method} {path}: {_describe(exc)}") from exc
        except ValueError as exc:
            raise SuperDocsResponseError(f"SuperDocs returned a non-JSON body for {method} {path}") from exc

    async def _send(self, method: str, path: str, timeout: float, **kwargs: Any) -> httpx.Response:
        """One request, retrying cheap transport faults.

        The gateway occasionally drops a multipart upload mid-flight
        (`RemoteProtocolError`). That fails in milliseconds and is worth retrying.

        A *timeout* is deliberately not retried. It costs the full timeout budget every
        attempt, so retrying a 300s upload three times would block generation for fifteen
        minutes and push the whole job past the server's own generation deadline. A
        timeout means the far side is genuinely struggling; report it and stop.
        """
        last: httpx.HTTPError | None = None
        for attempt in range(self.TRANSPORT_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.request(
                        method, f"{self.base_url}{path}", headers=self._headers, **kwargs
                    )
                    response.raise_for_status()
                    return response
            except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError) as exc:
                last = exc
                if attempt + 1 < self.TRANSPORT_RETRIES:
                    await asyncio.sleep(self.TRANSPORT_RETRY_BACKOFF * (attempt + 1))
        raise last  # type: ignore[misc]

    async def _request_bytes(self, method: str, path: str, timeout: float, **kwargs: Any) -> tuple[bytes, str]:
        """Like `_request`, for endpoints that return a file body rather than JSON."""
        try:
            response = await self._send(method, path, timeout, **kwargs)
            return response.content, response.headers.get("content-type", "")
        except httpx.HTTPStatusError as exc:
            raise SuperDocsResponseError(
                f"SuperDocs returned {exc.response.status_code} for {method} {path}: {exc.response.text[:300]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SuperDocsResponseError(f"SuperDocs request failed for {method} {path}: {_describe(exc)}") from exc

    async def upload_document(self, filename: str, content: bytes) -> dict[str, Any]:
        """Load one source document into the session as AI-queryable evidence.

        This posts to `/attachments/upload`, not `/documents/upload`. The two are easy to
        confuse and the difference is the whole integration: `/documents/upload` loads a
        file as *the active editable document*, so uploading eight source files simply
        replaced the editor's document eight times (every response came back with the
        same `document_id: "doc_primary"`). Nothing was retained as evidence, and the
        model answered the edit turn with "I couldn't detect any attached source
        documents in this session".

        Attachments are what the model can actually cite while editing.
        """
        payload = await self._request(
            "POST",
            "/attachments/upload",
            # SuperDocs extracts and indexes the file, so the wait scales with the
            # document, not the transfer. The seeded 1KB fixtures return in ~1.5s; a real
            # 2.7MB PDF exceeded a 120s budget and failed the whole run.
            timeout=self.UPLOAD_TIMEOUT,
            files={"file": (filename, content)},
            data={"session_id": self._session_id},
        )
        slug = filename.lower().replace(" ", "-")
        return {
            "document_id": f"{self._session_id}::{slug}",
            "session_id": self._session_id,
            "attachment_id": payload.get("attachment_id"),
            "processing_job_id": payload.get("job_id"),
            "filename": payload.get("filename", filename),
            "status": "uploaded",
            "bytes": len(content),
            "mode": "live",
        }

    async def _await_attachments(self, session_id: str) -> None:
        """Block until every attachment is indexed.

        Attachments are processed asynchronously and are not queryable until they finish.
        Sending the edit turn too early is indistinguishable from having uploaded nothing.
        """
        deadline = time.monotonic() + self.ATTACHMENT_TIMEOUT
        while True:
            try:
                payload = await self._request("GET", f"/attachments/status/{session_id}", timeout=60)
            except SuperDocsResponseError:
                return  # Status is advisory; let the edit turn report any real problem.

            items = payload.get("attachments") if isinstance(payload, dict) else payload
            states = [str((item or {}).get("status", "")).lower() for item in (items or [])]
            if not states or all(state in ("completed", "failed", "ready") for state in states):
                return
            if time.monotonic() >= deadline:
                raise SuperDocsResponseError(
                    f"SuperDocs did not finish processing the source documents within "
                    f"{self.ATTACHMENT_TIMEOUT:.0f}s (states: {sorted(set(states))})"
                )
            await asyncio.sleep(self.ATTACHMENT_POLL_INTERVAL)

    async def edit_document(
        self, document_id: str, instruction: str, document_html: str | None = None
    ) -> list[dict[str, Any]]:
        session_id = self._session_of(document_id)
        body: dict[str, Any] = {
            "session_id": session_id,
            "message": instruction,
            # HITL: the job pauses so the close pack's reviewers make the decisions.
            "approval_mode": "ask_every_time",
        }
        # The caller supplies the document being drafted. Without it there is nothing
        # for the model to revise, and the turn resolves as conversation rather than
        # a set of proposed changes.
        if document_html:
            body["document_html"] = document_html

        await self._await_attachments(session_id)
        started = await self._request("POST", "/chat/async", timeout=120, json=body)
        job_id = started.get("job_id")
        if not job_id:
            raise SuperDocsResponseError("SuperDocs /chat/async returned no job_id")

        job = await self._await_job(job_id)
        status = job.get("status")
        metadata = job.get("metadata") or {}

        if status in ("failed", "cancelled"):
            detail = str(job.get("error") or metadata.get("error") or status)[:300]
            raise SuperDocsResponseError(f"SuperDocs edit job {job_id} {status}: {detail}")
        if status == "awaiting_approval" and metadata.get("awaiting_kind") == "continue_prompt":
            raise SuperDocsResponseError(
                f"SuperDocs edit job {job_id} paused for a continue prompt, not a change review. "
                "The instruction was too large for a single turn."
            )

        pending = metadata.get("pending_changes")
        if not pending:
            raise SuperDocsResponseError(
                f"SuperDocs edit job {job_id} finished with status {status!r} and proposed no changes. "
                "There is nothing to review, so the pack was not generated."
            )

        changes = [self._to_contract_change(job_id, index, change) for index, change in enumerate(pending)]
        return parse_proposed_changes({"proposed_changes": changes})

    async def _await_job(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.EDIT_POLL_TIMEOUT
        while True:
            job = await self._request("GET", f"/jobs/{job_id}", timeout=60)
            if job.get("status") in ("awaiting_approval", "completed", "failed", "cancelled"):
                return job
            if time.monotonic() >= deadline:
                raise SuperDocsResponseError(
                    f"SuperDocs edit job {job_id} did not settle within {self.EDIT_POLL_TIMEOUT:.0f}s "
                    f"(last status {job.get('status')!r})"
                )
            await asyncio.sleep(self.EDIT_POLL_INTERVAL)

    @staticmethod
    def _to_contract_change(job_id: str, index: int, change: dict[str, Any]) -> dict[str, Any]:
        """Map one live `pending_changes` entry onto the close pack's change schema.

        `section`, `before_value` and `after_value` are required and must be non-empty,
        so an insert (no `old_html`) and a delete (no `new_html`) each get an explicit
        placeholder rather than failing validation.
        """
        before = _html_to_text(change.get("old_html") or "")
        after = _html_to_text(change.get("new_html") or "")
        operation = change.get("operation") or "edit"
        # Prefer the section's own label. Narrative sections read "Revenue summary: ..."
        # so the text before the colon is the heading a reviewer recognises; falling back
        # to the first 60 characters produces a title that is really a sentence fragment.
        label = (before or after or "").split(":", 1)[0].strip()
        section = label[:60] if 0 < len(label) <= 60 else (before or after or "")[:60].strip()
        section = section or f"Section {index + 1}"
        reference = change.get("ai_explanation") or f"SuperDocs {operation} on chunk {change.get('chunk_id')}"
        return {
            "external_change_id": f"{job_id}::{change.get('change_id')}",
            "section": section,
            "before_value": before or f"(no prior content - {operation})",
            "after_value": after or f"(content removed - {operation})",
            "source_reference": reference,
            "operation": operation,
            "chunk_id": change.get("chunk_id"),
            "superdocs_document_id": change.get("document_id"),
        }

    async def approve_changes(
        self, document_id: str, change_ids: list[str], rejected_change_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Submit the batch's decisions in a single call.

        SuperDocs reviews a whole batch at once: the top-level `approved` is the default
        for any change the request does not name, so a call carrying one change decides
        every other change in the batch too and completes the job. Approving item by item
        therefore did two bad things - the second and later clicks failed with
        `400 Job is not awaiting approval (status: completed)`, and the first click had
        already silently approved changes the reviewer went on to reject.

        Every decision is sent explicitly, rejections included, so the exported document
        contains exactly what was approved and nothing else.
        """
        session_id = self._session_of(document_id)
        rejected = list(rejected_change_ids or [])
        job_id, approved_ids = _split_change_ids(change_ids + rejected)
        approved_set = {cid.split("::", 1)[1] if "::" in cid else cid for cid in change_ids}

        payload = await self._request(
            "POST",
            f"/chat/{session_id}/approve",
            timeout=180,
            json={
                "job_id": job_id,
                # Required at the top level even when every entry carries its own flag.
                # False is the safe default for anything not named: never approve by
                # omission.
                "approved": False,
                "changes": [
                    {"change_id": cid, "approved": cid in approved_set} for cid in approved_ids
                ],
            },
        )
        return {
            "document_id": document_id,
            "session_id": session_id,
            "job_id": job_id,
            "approved_change_ids": sorted(change_ids),
            "rejected_change_ids": sorted(rejected),
            "status": payload.get("status", "approved"),
            "batch_complete": payload.get("batch_complete"),
            "request_id": payload.get("request_id") or job_id,
            "mode": "live",
        }

    async def export_document(
        self, document_id: str, approved_change_ids: list[str] | None = None
    ) -> dict[str, Any]:
        session_id = self._session_of(document_id)
        # A rejected change is never sent to SuperDocs, so its job can still be parked in
        # `awaiting_approval`, which blocks the session. Deny whatever was left undecided
        # so the exported document reflects exactly the approved set.
        await self._settle_pending_reviews(session_id)

        content, content_type = await self._request_bytes(
            "POST",
            "/documents/export",
            timeout=300,
            json={"session_id": session_id, "format": "pdf"},
        )
        if not content:
            raise SuperDocsResponseError("SuperDocs export returned an empty body")

        approved = sorted(approved_change_ids or [])
        return {
            "document_id": document_id,
            "session_id": session_id,
            "export_id": f"live-export-{_digest(session_id, *approved)[:16]}",
            "status": "exported",
            "format": "pdf",
            "content_type": content_type,
            "filename": f"{_stem(_slug_of(document_id))}-final.pdf",
            "approved_change_ids": approved,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "mode": "live",
        }

    async def _settle_pending_reviews(self, session_id: str) -> None:
        try:
            listing = await self._request("GET", f"/sessions/{session_id}/jobs", timeout=60)
        except SuperDocsResponseError:
            return  # Nothing visible to settle; let the export itself report any problem.

        jobs = listing.get("jobs") if isinstance(listing, dict) else listing
        for job in jobs or []:
            if not isinstance(job, dict) or job.get("status") != "awaiting_approval":
                continue
            metadata = job.get("metadata") or {}
            if metadata.get("awaiting_kind") == "continue_prompt":
                continue
            decided = set((metadata.get("pending_batch_decisions") or {}).keys())
            undecided = [
                change.get("change_id")
                for change in metadata.get("pending_changes") or []
                if change.get("change_id") and change.get("change_id") not in decided
            ]
            if not undecided:
                continue
            await self._request(
                "POST",
                f"/chat/{session_id}/approve",
                timeout=120,
                json={
                    "job_id": job.get("job_id") or job.get("id"),
                    "approved": False,
                    "changes": [{"change_id": cid, "approved": False} for cid in undecided],
                },
            )


class MockSuperDocsClient:
    """Deterministic offline stand-in, selected by SUPERDOCS_MODE=mock.

    Returns clearly synthetic proposed changes so the review queue has something to
    decide on without live credentials.
    """

    _CHANGES = [
        {
            "external_change_id": "change-revenue-1",
            "section": "Revenue Summary",
            "before_value": "Revenue increased by 5.1%.",
            "after_value": "Revenue increased by 8.4% based on the uploaded March memo.",
            "source_reference": "Revenue Memo.pdf, page 4",
        },
        {
            "external_change_id": "change-accrual-1",
            "section": "Accrual Exceptions",
            "before_value": "No material accrual exceptions noted.",
            "after_value": "One vendor accrual requires controller review before close.",
            "source_reference": "Accrual Support.pdf, page 2",
        },
        {
            "external_change_id": "change-bank-1",
            "section": "Checklist Footnote",
            "before_value": "Bank reconciliation pending.",
            "after_value": "Bank reconciliation completed with no unreconciled variance.",
            "source_reference": "Bank Recon.pdf, page 1",
        },
    ]

    async def upload_document(self, filename: str, content: bytes) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        slug = filename.lower().replace(" ", "-")
        return {
            "document_id": f"mock-{slug}",
            "status": "uploaded",
            "bytes": len(content),
            "request_id": "mock-upload-" + _digest(slug, hashlib.sha256(content).hexdigest())[:16],
            "mode": "mock",
        }

    async def edit_document(
        self, document_id: str, instruction: str, document_html: str | None = None
    ) -> list[dict[str, Any]]:
        await asyncio.sleep(0.05)
        # The working document does not affect the mock's output: determinism is the
        # point, and the fixed change set is what the tests pin.
        return parse_proposed_changes({"result": json.dumps(self._CHANGES)})

    async def approve_changes(
        self, document_id: str, change_ids: list[str], rejected_change_ids: list[str] | None = None
    ) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        ordered = sorted(change_ids)
        return {
            "document_id": document_id,
            "approved_change_ids": ordered,
            "status": "approved",
            # Derived from the inputs so the same approval always yields the same
            # receipt; nothing here comes from a live service.
            "request_id": "mock-approve-" + _digest(document_id, *ordered)[:16],
            "mode": "mock",
        }

    async def export_document(
        self, document_id: str, approved_change_ids: list[str] | None = None
    ) -> dict[str, Any]:
        await asyncio.sleep(0.05)
        from ...services.pdf import build_pdf

        approved = sorted(approved_change_ids or [])
        lines = [
            "Produced by the SuperDocs MOCK adapter. This is not live SuperDocs output.",
            "The bytes below are derived only from the inputs, so they are reproducible.",
            "",
            f"Working document id : {document_id}",
            f"Approved changes    : {len(approved)}",
        ]
        lines.extend(f"  - {change_id}" for change_id in approved)
        if not approved:
            lines.append("  (no changes were approved)")
        content = build_pdf("SuperDocs Export (mock)", lines)

        return {
            "document_id": document_id,
            "export_id": "mock-export-" + _digest(document_id, *approved)[:16],
            "status": "exported",
            "format": "pdf",
            "filename": f"{_stem(document_id)}-final.pdf",
            "approved_change_ids": approved,
            "content_base64": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
            "mode": "mock",
        }


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _stem(document_id: str) -> str:
    """Drop a trailing file extension so exports are not named `x.pdf-final.pdf`."""
    head, _, tail = document_id.rpartition(".")
    return head if head and 1 <= len(tail) <= 5 and tail.isalnum() else document_id


def current_mode() -> str:
    from ...core.config import settings

    return settings.superdocs_mode.strip().lower()


def get_client() -> SuperDocsClientProtocol:
    from ...core.config import settings

    mode = settings.superdocs_mode.strip().lower()
    if mode == "mock":
        return MockSuperDocsClient()
    if mode == "live":
        return SuperDocsClient(settings.superdocs_api_key, settings.superdocs_base_url)
    raise SuperDocsResponseError(f"Unknown SUPERDOCS_MODE {settings.superdocs_mode!r}; expected 'mock' or 'live'.")


def parse_proposed_changes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    nested = payload.get("result") or payload.get("proposed_changes")
    if isinstance(nested, str):
        try:
            nested = json.loads(nested)
        except json.JSONDecodeError as exc:
            raise SuperDocsResponseError("SuperDocs proposed changes were not valid JSON") from exc

    if not isinstance(nested, list):
        raise SuperDocsResponseError("SuperDocs proposed changes must be a list")

    for index, change in enumerate(nested):
        if not isinstance(change, dict):
            raise SuperDocsResponseError(f"Proposed change at index {index} is not an object")
        missing = [field for field in REQUIRED_CHANGE_FIELDS if not change.get(field)]
        if missing:
            raise SuperDocsResponseError(
                f"Proposed change at index {index} is missing required fields: {', '.join(missing)}"
            )

    return nested


def _describe(exc: Exception) -> str:
    """A non-empty description of a transport failure.

    Several httpx exceptions - `ReadTimeout` chief among them - stringify to the empty
    string, which produced the useless ledger entry "SuperDocs request failed for POST
    /documents/upload: " and told the operator nothing about what went wrong.
    """
    text = str(exc).strip()
    if text:
        return f"{type(exc).__name__}: {text}"
    if isinstance(exc, httpx.TimeoutException):
        return f"{type(exc).__name__}: the request timed out before SuperDocs responded"
    return type(exc).__name__


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _html_to_text(html: str) -> str:
    """Flatten a chunk of proposed-change html into the plain text the review UI shows."""
    text = _TAG_RE.sub(" ", html or "")
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(entity, char)
    return _WS_RE.sub(" ", text).strip()


def _slug_of(document_id: str) -> str:
    """The filename half of a `<session_id>::<slug>` document id."""
    return document_id.split("::", 1)[1] if "::" in document_id else document_id


def _split_change_ids(change_ids: list[str]) -> tuple[str, list[str]]:
    """Recover the shared job id and the bare change ids from `<job_id>::<change_id>`."""
    job_ids = {cid.split("::", 1)[0] for cid in change_ids if "::" in cid}
    if len(job_ids) > 1:
        raise SuperDocsResponseError(
            f"Cannot approve changes spanning multiple SuperDocs jobs: {sorted(job_ids)}"
        )
    if not job_ids:
        raise SuperDocsResponseError(
            "Change ids carry no SuperDocs job id. They were produced by a different "
            "SUPERDOCS_MODE; regenerate the pack in live mode before approving."
        )
    job_id = job_ids.pop()
    return job_id, [cid.split("::", 1)[1] for cid in change_ids]
