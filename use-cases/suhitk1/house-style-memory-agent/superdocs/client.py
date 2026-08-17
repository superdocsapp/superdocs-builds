"""SuperDocs client, fitted to the API as observed on 2026-08-13.

Built ON SuperDocs, never a version OF it.

This file was rewritten after the meter probe. The first version was written to
the brief's "minimum contract" and was wrong in several places: document_id
instead of session_id, proposed_changes instead of document_changes,
content_base64 instead of file_base64, approve_change without change_id. The
keyless suite passed anyway, because the fake shared the same wrong shapes —
exactly the failure mode Task 1 hit. Every shape below now comes from a real
captured response in tests/fixtures/real_responses/.

The double parse, verified against a real payload rather than assumed: the
JSON-RPC envelope is parsed once by the transport, and the MCP result's
`content[0].text` is *itself* a JSON-encoded string that must be parsed again.
After that second parse the value is an object and must not be parsed a third
time — a change whose text is literally `"[1, 2]"` has to survive as that text.

Billing, measured not assumed: an operation is charged only when a chat
actually edits the document. A chat that errors, or that produces no edit, is
free. That makes retries free, which the retry policy below relies on
explicitly rather than implicitly.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


class SuperDocsError(RuntimeError):
    def __init__(self, message: str, *, billed: bool = False,
                 tool: str = "", retryable: bool = False):
        super().__init__(message)
        self.billed = billed
        self.tool = tool
        self.retryable = retryable


class ProposedChangeParseError(SuperDocsError):
    """The double-parse contract was violated by the payload."""


class ApprovalError(SuperDocsError):
    """The approval batch did not complete, so no edit was applied."""


class Transport(Protocol):
    def call(self, tool: str, params: dict) -> dict: ...


# MEASURED 2026-08-13 (runs/meter_probe/probe.json). Not assumptions.
MEASURED_FREE_TOOLS = {
    "init_session", "upload_document_base64", "export_document",
    "request_download_url", "clear_cross_session_memory", "list_documents",
    "get_document_detail", "get_session_jobs", "get_job", "approve_change",
    "continue_chat", "get_account_status",
}
BILLABLE_TOOLS = {"chat", "chat_async"}

# Job states meaning "not finished yet". `in_progress` belongs here: treating
# it as terminal made an early approval attempt fail against a running job.
PENDING_JOB_STATES = {"queued", "pending", "running", "in_progress",
                      "processing"}


@dataclass
class OperationLedger:
    calls: dict[str, int] = field(default_factory=dict)
    billed: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    unbilled_chats: int = 0
    free_retries: int = 0

    def record(self, tool: str, *, failed: bool = False,
               ops_charged: int | None = None) -> None:
        self.calls[tool] = self.calls.get(tool, 0) + 1
        if failed:
            self.errors += 1
            return  # measured: an errored call is never billed
        if ops_charged:
            self.billed[tool] = self.billed.get(tool, 0) + ops_charged

    @property
    def total_operations(self) -> int:
        return sum(self.billed.values())

    @property
    def costs_are_confirmed(self) -> bool:
        return True

    def as_dict(self) -> dict:
        return {"calls": dict(self.calls), "billed": dict(self.billed),
                "total_operations": self.total_operations,
                "errors": self.errors, "unbilled_chats": self.unbilled_chats,
                "free_retries": self.free_retries,
                "costs_confirmed_by_probe": True,
                "cost_model_measured_on": "2026-08-13"}


def parse_proposed_content(value: Any) -> Any:
    """Resolve a JSON-encoded payload to an object. Parses at most once.

    - A JSON-encoded string is parsed. Once.
    - The result is already an object and is NOT parsed again, even when it is
      itself a string that looks like JSON.
    - An object is returned untouched.
    - A non-JSON string is a payload error, not a silent pass.
    """
    if isinstance(value, (dict, list)) or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProposedChangeParseError(
            f"content is a string but not JSON: {value[:80]!r}") from exc


@dataclass
class PendingChange:
    """One entry of document_changes.pending_changes, as the API returns it."""

    change_id: str
    operation: str = ""
    chunk_id: str = ""
    old_html: str = ""
    new_html: str = ""
    explanation: str = ""

    @classmethod
    def from_payload(cls, raw: Any) -> "PendingChange":
        data = parse_proposed_content(raw)
        if not isinstance(data, dict):
            raise ProposedChangeParseError(
                f"pending change did not resolve to an object: {type(data)}")
        return cls(change_id=data.get("change_id", ""),
                   operation=data.get("operation", "") or "",
                   chunk_id=data.get("chunk_id", "") or "",
                   old_html=data.get("old_html", "") or "",
                   new_html=data.get("new_html", "") or "",
                   explanation=data.get("ai_explanation", "") or "")


@dataclass
class ChatResult:
    response: str = ""
    session_id: str = ""
    updated_html: str = ""
    changes_summary: str = ""
    requires_approval: bool = False
    pending_changes: list[PendingChange] = field(default_factory=list)
    ops_charged: int = 0
    was_billable: bool = False
    ops_remaining: int | None = None
    raw: dict = field(default_factory=dict)

    @property
    def edited(self) -> bool:
        return bool(self.was_billable or self.pending_changes)


class SuperDocsClient:
    def __init__(self, transport: Transport,
                 ledger: OperationLedger | None = None):
        self.transport = transport
        self.ledger = ledger or OperationLedger()

    # --- plumbing ---------------------------------------------------------

    def _call(self, tool: str, params: dict) -> dict:
        try:
            response = self.transport.call(tool, params)
        except SuperDocsError:
            self.ledger.record(tool, failed=True)
            raise
        except Exception as exc:
            self.ledger.record(tool, failed=True)
            raise SuperDocsError(f"{tool} transport failure: {exc}",
                                 tool=tool, retryable=True) from exc
        if isinstance(response, dict) and response.get("error"):
            self.ledger.record(tool, failed=True)
            raise SuperDocsError(f"{tool} failed: {response['error']}",
                                 tool=tool,
                                 retryable=bool(response.get("retryable")))
        usage = response.get("usage") if isinstance(response, dict) else None
        charged = usage.get("ops_charged") if isinstance(usage, dict) else None
        if tool in BILLABLE_TOOLS and not charged:
            self.ledger.unbilled_chats += 1
        self.ledger.record(tool, ops_charged=charged)
        return response

    # --- sessions and documents -------------------------------------------

    def init_session(self, document_ids: list[str] | None = None) -> str:
        # document_ids must be present even when empty; an empty argument
        # object is rejected with HTTP 422.
        response = self._call("init_session",
                              {"document_ids": document_ids or []})
        session_id = response.get("session_id")
        if not session_id:
            raise SuperDocsError("init_session returned no session_id")
        return session_id

    def upload_document(self, session_id: str, filename: str,
                        content: bytes) -> dict:
        return self._call("upload_document_base64", {
            "filename": filename,
            "file_base64": base64.b64encode(content).decode("ascii"),
            "session_id": session_id})

    def export_document(self, session_id: str, fmt: str = "markdown") -> str:
        response = self._call("export_document",
                              {"session_id": session_id, "format": fmt})
        result = response.get("result", response.get("content", ""))
        return result if isinstance(result, str) else json.dumps(result)

    def request_download_url(self, session_id: str, fmt: str = "docx") -> str:
        return self._call("request_download_url",
                          {"session_id": session_id,
                           "format": fmt}).get("download_url", "")

    # --- chat -------------------------------------------------------------

    def chat(self, session_id: str, message: str, *,
             document_html: str | None = None,
             approval_mode: str = "approve_all",
             cross_session_memory: bool = False,
             cross_session_search: bool = False,
             cross_session_memory_key: str | None = None,
             cross_session_scope: list[str] | None = None) -> ChatResult:
        """One chat turn.

        `cross_session_memory_key` is the per-end-customer key — this is the
        primitive that keeps one client's voice out of another's document.
        `cross_session_scope` is a list of SESSION ids restricting search,
        which is a different thing and is NOT customer isolation.
        """
        params: dict[str, Any] = {
            "session_id": session_id, "message": message,
            "approval_mode": approval_mode,
            "cross_session_memory": cross_session_memory,
            "cross_session_search": cross_session_search}
        if document_html is not None:
            params["document_html"] = document_html
        if cross_session_memory_key:
            params["cross_session_memory_key"] = cross_session_memory_key
        if cross_session_scope:
            params["cross_session_scope"] = list(cross_session_scope)
        return self._to_result(self._call("chat", params))

    def _to_result(self, response: dict) -> ChatResult:
        changes = parse_proposed_content(response.get("document_changes") or {})
        if not isinstance(changes, dict):
            raise ProposedChangeParseError(
                "document_changes did not resolve to an object: "
                f"{type(changes).__name__}")
        usage = response.get("usage") or {}
        promotions = usage.get("promotions") or [{}]
        return ChatResult(
            response=response.get("response", ""),
            session_id=response.get("session_id", ""),
            updated_html=changes.get("updated_html") or "",
            changes_summary=changes.get("changes_summary") or "",
            requires_approval=bool(changes.get("requires_approval")),
            pending_changes=[PendingChange.from_payload(c)
                             for c in (changes.get("pending_changes") or [])],
            ops_charged=usage.get("ops_charged") or 0,
            was_billable=bool(usage.get("was_billable")),
            ops_remaining=promotions[0].get("ops_remaining"),
            raw=response)

    def chat_with_retry(self, session_id: str, message: str, *,
                        attempts: int = 3, backoff: float = 2.0,
                        **kwargs) -> ChatResult:
        """Retry a chat freely: a failed or no-op chat costs nothing.

        Measured 2026-08-13: an errored chat (HTTP 422) and a chat producing no
        edit are both billed 0; only an applied edit is charged. Retrying is
        therefore a latency cost, never an operations cost, so this policy does
        not trade reliability against budget. Retries are counted separately as
        `free_retries` so the run report can show they cost nothing.
        """
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                result = self.chat(session_id, message, **kwargs)
            except SuperDocsError as exc:
                last = exc
                if not exc.retryable or attempt == attempts:
                    raise
                self.ledger.free_retries += 1
                time.sleep(backoff * attempt)
                continue
            if result.edited or attempt == attempts:
                return result
            self.ledger.free_retries += 1   # a no-op chat is unbilled
            time.sleep(backoff * attempt)
        raise last or SuperDocsError("chat failed with no result")

    # --- explicit approval flow -------------------------------------------

    def chat_async(self, session_id: str, message: str, *,
                   approval_mode: str = "ask_every_time", **kwargs) -> str:
        params: dict[str, Any] = {"session_id": session_id, "message": message,
                                  "approval_mode": approval_mode}
        for key in ("document_html", "cross_session_memory",
                    "cross_session_search", "cross_session_memory_key",
                    "cross_session_scope"):
            if kwargs.get(key) is not None:
                params[key] = kwargs[key]
        job_id = self._call("chat_async", params).get("job_id")
        if not job_id:
            raise SuperDocsError("chat_async returned no job_id")
        return job_id

    def wait_for_job(self, job_id: str, *, tries: int = 40,
                     interval: float = 2.0) -> dict:
        job: dict = {}
        for _ in range(tries):
            response = self._call("get_job", {"job_id": job_id})
            job = response.get("job", response)
            if job.get("status") not in PENDING_JOB_STATES:
                return job
            time.sleep(interval)
        raise SuperDocsError(
            f"job {job_id} still {job.get('status')!r} after {tries} polls")

    def pending_changes_of(self, job: dict) -> list[PendingChange]:
        raw = (job.get("metadata") or {}).get("pending_changes") or []
        return [PendingChange.from_payload(c) for c in raw]

    def approve_change(self, session_id: str, job_id: str, change_id: str,
                       approved: bool = True,
                       feedback: str | None = None) -> dict:
        """Approve ONE change by id.

        `change_id` is required in practice. Approving with only a job_id
        returns `batch_complete: false` and the edit is never applied — the
        call succeeds and nothing happens, which is the worst kind of failure.
        Verified against the live service on 2026-08-13.
        """
        if not change_id:
            raise ApprovalError(
                "approve_change requires a change_id; approving a job without "
                "one leaves the batch incomplete and applies nothing")
        params: dict[str, Any] = {"session_id": session_id, "job_id": job_id,
                                  "change_id": change_id, "approved": approved}
        if feedback:
            params["feedback"] = feedback
        return self._call("approve_change", params)

    def approve_all_pending(self, session_id: str, job_id: str,
                            changes: list[PendingChange]) -> int:
        """Approve every pending change, then verify the batch completed."""
        if not changes:
            return 0
        result: dict = {}
        for change in changes:
            result = self.approve_change(session_id, job_id, change.change_id)
        if not result.get("batch_complete"):
            raise ApprovalError(
                f"approval batch did not complete after {len(changes)} "
                f"approvals: {result}. No edit has been applied.")
        return len(changes)

    # --- memory primitives ------------------------------------------------

    def clear_cross_session_memory(self, memory_key: str | None = None) -> int:
        params = {"memory_key": memory_key} if memory_key else {}
        response = self._call("clear_cross_session_memory", params)
        removed = response.get("removed")
        if not isinstance(removed, int):
            raise SuperDocsError(
                f"clear_cross_session_memory returned {removed!r}, expected an "
                "int under 'removed'")
        return removed
