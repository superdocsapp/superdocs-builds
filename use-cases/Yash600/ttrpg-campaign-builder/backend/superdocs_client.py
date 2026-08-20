"""
superdocs_client.py

Thin, dependency-light wrapper around the SuperDocs REST API
(https://docs.superdocs.app). Shared by both Task 2 builds
(healthcare-privacy-pack and, later, the TTRPG campaign-doc builder).

Design notes (learned by probing the live API before writing this file —
see the empirical checks in the build chat; every shape below was observed
from a real response, not guessed from the OpenAPI schema alone):

- Uploading a document via /v1/documents/upload-base64 PRESERVES any
  data-chunk-id attributes already present in the HTML you send. That is
  the entire foundation of the deterministic dependency model in this
  project: we author policy sections and procedures with fixed chunk ids
  ("policy-sec-1", ..., "proc-access-control", ...) so that edges we store
  in Postgres never have to be re-discovered after an edit.
- GET /v1/documents (list) returns the *durable* document_id you store and
  reuse. GET /v1/sessions/{id}/documents returns a *session-scoped*
  document_id (e.g. "doc_primary") plus a "durable_document_id" field that
  matches the one above -- don't confuse the two.
- GET /v1/documents/{id} returns a non-billable "structure" field
  (headings/section_count/block_count) -- this is the cheap way the
  validator confirms a heading still exists without paying for an edit or
  a full export. Pass include_html=true to also get the raw HTML (still
  non-billable; billing is on /v1/chat and /v1/chat/async only, per the
  usage.was_billable flag observed on every chat call and its absence on
  GET calls).
- The "double JSON parse" gotcha is real but narrower than it first
  sounds: JobResponse.metadata.pending_changes (top-level) already comes
  back as parsed objects. The trap is in
  JobResponse.metadata.intermediate_responses[i].content when
  intermediate_responses[i].type == "proposed_change_batch" -- that
  "content" field is a JSON-encoded STRING (a string containing
  `{"type": "single_approval", ..., "changes": [...]}`) that needs a
  second json.loads() before you can read .changes out of it. This client
  prefers metadata.pending_changes when present and only falls back to
  parsing intermediate_responses if it isn't (e.g. after inspecting a
  completed job's history).
- Async jobs go pending -> in_progress -> awaiting_approval (if
  approval_mode="ask_every_time") -> completed, or straight to completed
  if approval_mode="approve_all" (default). There is no fixed timing --
  poll with backoff, not a fixed sleep.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Iterable

import requests

DEFAULT_BASE_URL = "https://api.superdocs.app"


class SuperDocsError(RuntimeError):
    """Raised for any non-2xx response from the SuperDocs API."""

    def __init__(self, status_code: int, url: str, body: Any):
        self.status_code = status_code
        self.url = url
        self.body = body
        super().__init__(f"SuperDocs API error {status_code} on {url}: {body}")


class SuperDocsJobTimeout(RuntimeError):
    """Raised when poll_job_until_done exceeds its timeout."""


@dataclass
class PendingChange:
    """Normalized view of one proposed edit awaiting approval."""

    change_id: str
    operation: str
    chunk_id: str | None
    document_id: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str | None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "PendingChange":
        return cls(
            change_id=raw["change_id"],
            operation=raw.get("operation", "edit"),
            chunk_id=raw.get("chunk_id"),
            document_id=raw.get("document_id"),
            old_html=raw.get("old_html"),
            new_html=raw.get("new_html"),
            ai_explanation=raw.get("ai_explanation"),
        )


class SuperDocsClient:
    """
    Synchronous SuperDocs API client. Deliberately sync + `requests`-based:
    FastAPI runs sync `def` route handlers in a worker thread automatically,
    so this stays simple without dragging async/await through every call
    site for an S2-scoped build.
    """

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, timeout: int = 60):
        if not api_key:
            raise ValueError("SuperDocsClient requires an api_key (sk_...)")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------ #
    # low-level request helper
    # ------------------------------------------------------------------ #

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        resp = self._session.request(method, url, timeout=self.timeout, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise SuperDocsError(resp.status_code, url, body)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.content  # binary (e.g. export)

    # ------------------------------------------------------------------ #
    # account
    # ------------------------------------------------------------------ #

    def whoami(self) -> dict:
        """GET /v1/agents/whoami -- cheap, non-billable quota check."""
        return self._request("GET", "/v1/agents/whoami")

    def verify_key(self) -> bool:
        """GET /v1/sessions -- the documented cheap way to verify a key."""
        try:
            self._request("GET", "/v1/sessions")
            return True
        except SuperDocsError:
            return False

    # ------------------------------------------------------------------ #
    # documents
    # ------------------------------------------------------------------ #

    def upload_document_base64(
        self,
        filename: str,
        html_or_bytes: str | bytes,
        session_id: str,
        return_html: bool = True,
        is_html_text: bool = True,
    ) -> dict:
        """
        POST /v1/documents/upload-base64

        For this project we always upload verbatim, pre-authored HTML with
        our own data-chunk-id attributes already baked in -- SuperDocs
        preserves them rather than reassigning its own ids, which is what
        makes the whole dependency-hash model possible.
        """
        if is_html_text and isinstance(html_or_bytes, str):
            raw_bytes = html_or_bytes.encode("utf-8")
        elif isinstance(html_or_bytes, bytes):
            raw_bytes = html_or_bytes
        else:
            raw_bytes = str(html_or_bytes).encode("utf-8")

        file_b64 = base64.b64encode(raw_bytes).decode("ascii")
        payload = {
            "filename": filename,
            "file_base64": file_b64,
            "session_id": session_id,
            "return_html": return_html,
        }
        return self._request("POST", "/v1/documents/upload-base64", json=payload)

    def upload_image_base64(self, filename: str, image_bytes: bytes) -> dict:
        """
        POST /v1/documents/images/upload-base64 -> stable <img src> URL.

        NOTE: unlike upload_document_base64/upload_template_base64 (which take
        `file_base64`), this endpoint's request body field is `image_base64`.
        Sending `file_base64` here gets a 422 "Field required" from the live
        API even though the sibling endpoints use the other name.
        """
        payload = {
            "filename": filename,
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        }
        return self._request("POST", "/v1/documents/images/upload-base64", json=payload)

    def upload_template_base64(self, filename: str, html_or_bytes: str | bytes) -> dict:
        """POST /v1/templates/upload-base64"""
        raw_bytes = html_or_bytes.encode("utf-8") if isinstance(html_or_bytes, str) else html_or_bytes
        payload = {
            "filename": filename,
            "file_base64": base64.b64encode(raw_bytes).decode("ascii"),
        }
        return self._request("POST", "/v1/templates/upload-base64", json=payload)

    def list_templates(self) -> dict:
        """GET /v1/templates -- non-billable."""
        return self._request("GET", "/v1/templates")

    def delete_template(self, template_id: str) -> dict:
        """DELETE /v1/templates/{template_id}"""
        return self._request("DELETE", f"/v1/templates/{template_id}")

    def list_documents(self) -> dict:
        return self._request("GET", "/v1/documents")

    def get_document(self, document_id: str, include_html: bool = False) -> dict:
        """
        GET /v1/documents/{id} -- returns the non-billable `structure`
        field (headings/section_count/block_count) used by the validator,
        plus raw HTML when include_html=True.
        """
        params = {"include_html": "true"} if include_html else {}
        return self._request("GET", f"/v1/documents/{document_id}", params=params)

    # ------------------------------------------------------------------ #
    # sessions (multi-document)
    # ------------------------------------------------------------------ #

    def init_session(self, document_ids: Iterable[str] | None = None, session_id: str | None = None) -> dict:
        """POST /v1/sessions/init -- start a session with documents already open."""
        payload: dict[str, Any] = {}
        if document_ids:
            payload["document_ids"] = list(document_ids)
        if session_id:
            payload["session_id"] = session_id
        return self._request("POST", "/v1/sessions/init", json=payload)

    def open_documents(self, session_id: str, document_ids: Iterable[str]) -> dict:
        """POST /v1/sessions/{session_id}/documents/open"""
        payload = {"document_ids": list(document_ids)}
        return self._request("POST", f"/v1/sessions/{session_id}/documents/open", json=payload)

    def list_session_documents(self, session_id: str) -> dict:
        return self._request("GET", f"/v1/sessions/{session_id}/documents")

    # ------------------------------------------------------------------ #
    # chat (edit) -- sync
    # ------------------------------------------------------------------ #

    def chat(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str | None = None,
        model_tier: str | None = None,
    ) -> dict:
        """POST /v1/chat -- synchronous edit/create. Use for small, fast turns."""
        payload: dict[str, Any] = {"message": message, "session_id": session_id}
        if document_html is not None:
            payload["document_html"] = document_html
        if approval_mode:
            payload["approval_mode"] = approval_mode
        if model_tier:
            payload["model_tier"] = model_tier
        return self._request("POST", "/v1/chat", json=payload)

    # ------------------------------------------------------------------ #
    # chat (edit) -- async + HITL approval
    # ------------------------------------------------------------------ #

    def chat_async(
        self,
        session_id: str,
        message: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str | None = None,
    ) -> dict:
        """
        POST /v1/chat/async -- returns {job_id, session_id, status:"pending"}
        immediately. This is the workhorse for the change-propagation flow:
        every stale procedure gets its own chat/async call with
        approval_mode="ask_every_time" so a human reviews each proposed
        edit independently.
        """
        payload: dict[str, Any] = {
            "message": message,
            "session_id": session_id,
            "async_mode": True,
            "approval_mode": approval_mode,
        }
        if document_html is not None:
            payload["document_html"] = document_html
        if model_tier:
            payload["model_tier"] = model_tier
        return self._request("POST", "/v1/chat/async", json=payload)

    def get_job(self, job_id: str) -> dict:
        """GET /v1/jobs/{job_id}"""
        return self._request("GET", f"/v1/jobs/{job_id}")

    def poll_job_until_done(
        self,
        job_id: str,
        terminal_statuses: tuple[str, ...] = ("awaiting_approval", "completed", "failed", "cancelled"),
        initial_interval: float = 2.0,
        max_interval: float = 15.0,
        backoff_factor: float = 1.5,
        timeout: float = 600.0,
    ) -> dict:
        """
        Poll-with-backoff helper for the "operations can silently take
        minutes" behavior SuperDocs' own docs warn about. Starts at
        initial_interval seconds, multiplies by backoff_factor each miss,
        caps at max_interval, gives up after timeout seconds.
        """
        start = time.monotonic()
        interval = initial_interval
        while True:
            job = self.get_job(job_id)
            if job.get("status") in terminal_statuses:
                return job
            if time.monotonic() - start > timeout:
                raise SuperDocsJobTimeout(
                    f"Job {job_id} did not reach a terminal status within {timeout}s "
                    f"(last status={job.get('status')})"
                )
            time.sleep(interval)
            interval = min(interval * backoff_factor, max_interval)

    @staticmethod
    def extract_pending_changes(job: dict) -> list[PendingChange]:
        """
        Normalize a job's proposed changes regardless of where they live.

        Preferred source: job["metadata"]["pending_changes"] -- already a
        list of plain dicts, present when status == "awaiting_approval".

        Fallback: job["metadata"]["intermediate_responses"], scanning for
        entries with type == "proposed_change_batch". THIS is the field
        that needs the second json.loads(): entry["content"] is a JSON
        string, not an object, e.g.
            '{"type": "single_approval", "batch_id": "...", "changes": [...]}'
        """
        metadata = job.get("metadata") or {}

        raw_changes = metadata.get("pending_changes")
        if raw_changes:
            return [PendingChange.from_raw(c) for c in raw_changes]

        changes: list[PendingChange] = []
        for entry in metadata.get("intermediate_responses") or []:
            if entry.get("type") != "proposed_change_batch":
                continue
            content = entry.get("content")
            if not isinstance(content, str):
                continue
            try:
                parsed = json.loads(content)  # <-- the documented second parse
            except (TypeError, json.JSONDecodeError):
                continue
            for raw in parsed.get("changes", []):
                changes.append(PendingChange.from_raw(raw))
        return changes

    def approve_change(
        self,
        session_id: str,
        job_id: str,
        change_id: str | None = None,
        approved: bool = True,
        feedback: str | None = None,
    ) -> dict:
        """POST /v1/chat/{session_id}/approve -- approve/deny one change."""
        payload: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id:
            payload["change_id"] = change_id
        if feedback:
            payload["feedback"] = feedback
        return self._request("POST", f"/v1/chat/{session_id}/approve", json=payload)

    def approve_changes_batch(
        self, session_id: str, job_id: str, decisions: list[dict[str, Any]]
    ) -> dict:
        """
        POST /v1/chat/{session_id}/approve with a `changes` array --
        batch accept/deny. decisions: [{"change_id": ..., "approved": bool,
        "feedback": str | None}, ...]
        """
        payload = {"job_id": job_id, "approved": True, "changes": decisions}
        return self._request("POST", f"/v1/chat/{session_id}/approve", json=payload)

    # ------------------------------------------------------------------ #
    # export
    # ------------------------------------------------------------------ #

    def export(
        self,
        session_id: str | None = None,
        html: str | None = None,
        fmt: str = "docx",
        filename: str | None = None,
    ) -> bytes:
        """
        POST /v1/documents/export -- exports never cost ops (only chat
        edits/searches are billable, confirmed via usage.was_billable
        being present only on /v1/chat and /v1/chat/async responses).
        Returns raw file bytes (this endpoint streams the file directly,
        it is not JSON).
        """
        payload: dict[str, Any] = {"format": fmt}
        if session_id:
            payload["session_id"] = session_id
        if html:
            payload["html"] = html
        if filename:
            payload["options"] = {"filename": filename}

        url = f"{self.base_url}/v1/documents/export"
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise SuperDocsError(resp.status_code, url, body)
        return resp.content
