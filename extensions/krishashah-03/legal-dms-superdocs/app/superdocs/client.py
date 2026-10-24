"""
Thin wrapper around the real SuperDocs REST API.

Every request/response shape here was checked against the live OpenAPI spec
at https://api.superdocs.app/openapi.json AND validated live via Postman
against a real account (see project notes) - not guessed from the schema
alone. Two real discrepancies were found and fixed here:

1. metadata.pending_changes items use change_id / operation / old_html /
   new_html / ai_explanation - NOT the summary / diff_html field names
   originally guessed from the schema alone. _parse_pending_changes() now
   reads the real fields.

2. get_job() was reading the final document HTML from result.updated_html -
   one level too shallow. The real path (confirmed from a live completed
   job) is result.document_changes.updated_html. This silently returned
   None before - no error, just missing data - which would have broken
   workflow.py's post-approval HTML cache refresh without ever raising.

Two practical gotchas the task brief calls out, both handled here:
  1. Proposed-change content in job metadata CAN arrive as a JSON-encoded
     string in some contexts (confirmed: the nested proposed_change_batch
     entry inside metadata.intermediate_responses, which this client does
     not currently parse) - _parse_pending_changes() still defensively
     re-parses top-level pending_changes items in case that ever changes,
     even though live testing showed them as plain dicts today.
  2. Long-running jobs can sit at status="processing" for tens of seconds to
     minutes with no error - poll_job() treats that as normal, not a failure.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Literal

import requests

ApprovalMode = Literal["approve_all", "ask_every_time"]
ModelTier = Literal["core", "turbo", "pro", "max"]
ExportFormat = Literal["docx", "pdf", "html", "markdown", "txt"]


class SuperDocsAPIError(RuntimeError):
    """Raised for any non-2xx response from SuperDocs, with the parsed detail."""

    def __init__(self, status_code: int, detail: Any):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"SuperDocs API error {status_code}: {detail}")


class SuperDocsJobTimeoutError(RuntimeError):
    """Raised by poll_job() when a job doesn't settle within the given budget."""


@dataclass
class PendingChange:
    """
    One AI-proposed edit awaiting human approval. Field names match the REAL
    API response (confirmed via live Postman testing on 2026-08-12), not the
    OpenAPI schema's implied names:

        change_id   - the id to pass back to approve_changes_for_session
        chunk_id    - which chunk this touches. For operation="create" this
                      is literally the string "new", not a stable location -
                      don't treat it as a real chunk reference in that case.
        operation   - "create" | "update" | "delete" (confirmed: "create")
        old_html    - the section's HTML before the change (None for a create)
        new_html    - the proposed HTML for the section
        ai_explanation - the AI's own human-readable summary of what/why,
                      e.g. "(check) I have added a paragraph stating..."
        document_id - which document in the session this applies to
                      (e.g. "doc_primary" - relevant once we touch
                      multi-document sessions, not used yet)
    """

    change_id: str
    chunk_id: str | None
    operation: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str | None
    document_id: str | None
    raw: dict


@dataclass
class JobState:
    job_id: str
    status: str  # pending | processing | awaiting_approval | completed | failed | cancelled
    pending_changes: list[PendingChange]
    document_html: str | None
    raw: dict


class SuperDocsClient:
    """
    Synchronous client for the calls this integration is built on (upload,
    chat/async + approve, export), plus job polling and the attachments call
    used only for precedent-search AI context.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.superdocs.app",
        session: requests.Session | None = None,
        request_timeout: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("SuperDocsClient requires a non-empty api_key")
        self._base_url = base_url.rstrip("/")
        self._timeout = request_timeout
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    # ---------- low-level request helper ----------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self._base_url}{path}"
        response = self._session.request(method, url, timeout=self._timeout, **kwargs)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise SuperDocsAPIError(response.status_code, detail)
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return {"_raw_bytes": response.content}

    # ---------- 1. upload ----------

    def upload_document_base64(
        self,
        filename: str,
        file_base64: str,
        session_id: str,
        return_html: bool = True,
    ) -> dict:
        """
        POST /v1/documents/upload-base64
        Loads the file as the ACTIVE, editable document in `session_id`.
        Confirmed working as-is via live Postman test (Step 2).
        """
        body = {
            "filename": filename,
            "file_base64": file_base64,
            "session_id": session_id,
            "return_html": return_html,
        }
        return self._request("POST", "/v1/documents/upload-base64", json=body)

    # ---------- 2. edit (async, human-in-the-loop) ----------

    def chat_async(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: ApprovalMode = "ask_every_time",
        model_tier: ModelTier | None = None,
        response_mode: Literal["full", "compact"] = "full",
    ) -> str:
        """
        POST /v1/chat/async
        Confirmed working via live Postman test (Step 3) - but ONLY once
        document_html was included. Without it, the AI has nothing to edit,
        asks a clarifying question instead, and the job still reaches
        status="completed" with no error. Callers (see workflow.py) MUST
        always pass document_html - this client does not enforce that
        itself, since it has no way to know what "current" means; that's
        workflow.py's job via its per-session HTML cache.
        Returns the job_id to poll.
        """
        body: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "approval_mode": approval_mode,
            "response_mode": response_mode,
        }
        if document_html is not None:
            body["document_html"] = document_html
        if model_tier is not None:
            body["model_tier"] = model_tier
        result = self._request("POST", "/v1/chat/async", json=body)
        return result["job_id"]

    def get_job(self, job_id: str) -> JobState:
        """
        GET /v1/jobs/{job_id} - current status plus any pending changes.

        document_html is read from result.document_changes.updated_html -
        confirmed via a live completed job's actual response shape. The
        original code checked result.updated_html directly (one level too
        shallow) and would have silently returned None here.
        """
        result = self._request("GET", f"/v1/jobs/{job_id}")
        pending = _parse_pending_changes(result)

        document_html = None
        job_result = result.get("result")
        if isinstance(job_result, dict):
            document_changes = job_result.get("document_changes")
            if isinstance(document_changes, dict):
                document_html = document_changes.get("updated_html")

        return JobState(
            job_id=job_id,
            status=result.get("status", "unknown"),
            pending_changes=pending,
            document_html=document_html,
            raw=result,
        )

    def poll_job(
        self,
        job_id: str,
        stop_statuses: tuple[str, ...] = ("awaiting_approval", "completed", "failed", "cancelled"),
        interval_seconds: float = 2.0,
        timeout_seconds: float = 600.0,
        sleep_fn=time.sleep,
    ) -> JobState:
        """
        Poll until the job reaches one of stop_statuses. A long silent wait
        (thirty seconds to a few minutes on big documents, per the task
        brief, and confirmed live - our test job took ~6 seconds even on a
        two-sentence document) is expected and is NOT treated as an error
        here - only an explicit timeout_seconds budget being exceeded raises.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            state = self.get_job(job_id)
            if state.status in stop_statuses:
                return state
            if time.monotonic() >= deadline:
                raise SuperDocsJobTimeoutError(
                    f"Job {job_id} did not reach {stop_statuses} within {timeout_seconds}s "
                    f"(last status: {state.status})"
                )
            sleep_fn(interval_seconds)

    # ---------- 3. approve ----------

    def approve_changes_for_session(
        self,
        session_id: str,
        job_id: str,
        decisions: list[dict],
    ) -> JobState:
        """
        POST /v1/chat/{session_id}/approve
        `decisions` is a list of {"change_id": ..., "approved": bool, "feedback": str|None}.
        Confirmed working exactly as written via live Postman test (Step 5) -
        real response was {"status": "ok", "message": "Approval processed",
        "batch_complete": true}. Approved changes apply atomically; denied
        ones are discarded without touching the rest.
        """
        body = {"job_id": job_id, "changes": decisions}
        body["approved"] = all(d.get("approved") for d in decisions) if decisions else True
        self._request("POST", f"/v1/chat/{session_id}/approve", json=body)
        return self.get_job(job_id)

    # ---------- 4. export ----------

    def export_document(
        self,
        format: ExportFormat = "docx",
        html: str | None = None,
        session_id: str | None = None,
        options: dict | None = None,
    ) -> bytes:
        """
        POST /v1/documents/export
        Exactly one of html / session_id should be supplied. Confirmed
        working via live Postman test (Step 7) - produced a real, openable
        .docx with the approved 2-year clause present.
        """
        if not html and not session_id:
            raise ValueError("export_document requires either html or session_id")
        body: dict[str, Any] = {"format": format}
        if html is not None:
            body["html"] = html
        if session_id is not None:
            body["session_id"] = session_id
        if options:
            body["options"] = options

        url = f"{self._base_url}/v1/documents/export"
        response = self._session.post(url, json=body, timeout=self._timeout)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise SuperDocsAPIError(response.status_code, detail)
        return response.content

    # ---------- attachments (precedent-search AI context only) ----------

    def upload_attachment_base64(
        self,
        filename: str,
        file_base64: str,
        session_id: str,
    ) -> str:
        """
        POST /v1/attachments/upload-base64
        Loads a READ-ONLY reference file the AI can search/summarize, but
        never edits. Used only by the precedent-search "AI summary" feature.
        Returns a job_id; poll GET /v1/attachments/status/{session_id} (or
        GET /v1/jobs/{job_id}, same underlying job store) to know when
        indexed.
        """
        body = {"filename": filename, "file_base64": file_base64, "session_id": session_id}
        result = self._request("POST", "/v1/attachments/upload-base64", json=body)
        return result["job_id"]


def _parse_pending_changes(job_result: dict) -> list[PendingChange]:
    """
    Maps metadata.pending_changes items to PendingChange using the REAL
    field names confirmed via live Postman testing:

        change_id, operation, chunk_id, document_id, old_html, new_html,
        ai_explanation

    Live testing showed these arrive as plain dicts, not JSON-encoded
    strings - unlike the nested metadata.intermediate_responses entry of
    type "proposed_change_batch", which IS a JSON-encoded string (not parsed
    by this client currently - it carries extra positional detail like
    insert_after_chunk_id that pending_changes doesn't, useful for a richer
    review UI later, not needed for the core workflow). The defensive
    string-parse below is kept as a safety net in case that ever changes for
    pending_changes itself, even though it wasn't needed in practice.
    """
    metadata = job_result.get("metadata") or {}
    raw_changes = metadata.get("pending_changes") or []
    parsed: list[PendingChange] = []
    for item in raw_changes:
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError:
                item = {"change_id": None, "raw_unparsed": item}
        parsed.append(
            PendingChange(
                change_id=item.get("change_id") or item.get("id") or "",
                chunk_id=item.get("chunk_id"),
                operation=item.get("operation"),
                old_html=item.get("old_html"),
                new_html=item.get("new_html"),
                ai_explanation=item.get("ai_explanation") or item.get("summary"),
                document_id=item.get("document_id"),
                raw=item,
            )
        )
    return parsed
