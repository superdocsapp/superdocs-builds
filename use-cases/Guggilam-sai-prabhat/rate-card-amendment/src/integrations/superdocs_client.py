"""Thin async JSON-RPC client for the SuperDocs MCP API.

SuperDocs (https://api.superdocs.app/mcp) is a real, external document-editing
service reached over MCP/JSON-RPC 2.0 (`tools/call`), not a Python library.
This module wraps exactly the tool calls this application needs — upload,
scoped chat_async edit proposals, job polling, per-change approval, and
export — behind a small async client so the rest of the app never touches
JSON-RPC framing directly.

Every function takes an `httpx.AsyncClient` so tests can inject a mock
transport (see `tests/integration/superdocs_fixtures.py`) instead of making
live network calls. The Bearer token is read from `SUPERDOCS_API_KEY` and is
never hardcoded.

Two independent JSON parses happen on every `poll_job` call: the outer
MCP JSON-RPC envelope (`result.content[0].text`), and that text itself,
which is a *second*, independent JSON document containing the job's
`pending_changes`/`document_changes`. Both are wrapped so a malformed or
truncated response raises `SuperDocsParseError` — named per the app's
failure contract (what/likely_cause/next_action) — rather than crashing
with a raw `JSONDecodeError` or silently returning an empty list.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

SUPERDOCS_MCP_URL = "https://api.superdocs.app/mcp"
_JSONRPC_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class SuperDocsError(Exception):
    """Base class for structured SuperDocs failures.

    Every instance carries `what`, `likely_cause`, and `next_action` so
    callers can surface a failure message that never hides what happened.
    """

    def __init__(self, what: str, likely_cause: str, next_action: str) -> None:
        self.what = what
        self.likely_cause = likely_cause
        self.next_action = next_action
        super().__init__(what)

    def to_dict(self) -> dict[str, str]:
        return {
            "what": self.what,
            "likely_cause": self.likely_cause,
            "next_action": self.next_action,
        }


class SuperDocsTransportError(SuperDocsError):
    """The HTTP call to SuperDocs itself failed (network, timeout, non-2xx)."""


class SuperDocsRpcError(SuperDocsError):
    """SuperDocs returned a JSON-RPC-level error object."""


class SuperDocsParseError(SuperDocsError):
    """A response body could not be parsed where valid JSON was expected.

    Covers both the outer JSON-RPC envelope and the inner
    `result.content[0].text` JSON document (the "second JSON parse").
    """


def _api_key() -> str:
    key = os.environ.get("SUPERDOCS_API_KEY")
    if not key:
        raise SuperDocsError(
            what="SUPERDOCS_API_KEY is not set",
            likely_cause="the environment variable was never exported before starting the backend",
            next_action="set SUPERDOCS_API_KEY to a valid sk_... key and restart the process",
        )
    return key


async def _call_tool(
    client: httpx.AsyncClient,
    tool_name: str,
    arguments: dict[str, Any],
    request_id: int = 1,
) -> dict[str, Any]:
    """POST one JSON-RPC tools/call request and return the parsed envelope's `result`."""

    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {**_JSONRPC_HEADERS, "Authorization": f"Bearer {_api_key()}"}

    try:
        response = await client.post(SUPERDOCS_MCP_URL, json=payload, headers=headers, timeout=60.0)
    except httpx.TimeoutException as exc:
        raise SuperDocsTransportError(
            what=f"SuperDocs tool call '{tool_name}' timed out",
            likely_cause="SuperDocs took longer than 60s to respond, possibly a large document or model contention",
            next_action="retry the call; if it keeps timing out, reduce the document size or instruction scope",
        ) from exc
    except httpx.HTTPError as exc:
        raise SuperDocsTransportError(
            what=f"SuperDocs tool call '{tool_name}' failed at the transport layer",
            likely_cause=str(exc),
            next_action="check network connectivity to api.superdocs.app and retry",
        ) from exc

    if response.status_code >= 400:
        raise SuperDocsTransportError(
            what=f"SuperDocs tool call '{tool_name}' returned HTTP {response.status_code}",
            likely_cause=response.text[:500],
            next_action="check the SUPERDOCS_API_KEY is valid and the account has remaining quota (get_account_status)",
        )

    try:
        envelope = response.json()
    except ValueError as exc:
        raise SuperDocsParseError(
            what=f"could not parse the JSON-RPC envelope for '{tool_name}'",
            likely_cause="SuperDocs returned a non-JSON or truncated HTTP body",
            next_action="retry the call; if persistent, this is a SuperDocs-side outage — check https://api.superdocs.app health",
        ) from exc

    if "error" in envelope:
        error = envelope["error"]
        raise SuperDocsRpcError(
            what=f"SuperDocs tool '{tool_name}' returned a JSON-RPC error",
            likely_cause=str(error.get("message", error)),
            next_action="inspect the arguments sent to this tool call and correct them before retrying",
        )

    result = envelope.get("result", {})

    # SuperDocs also signals tool-level failures via result.isError=true with
    # a plain-text (not JSON) message in content[0].text, distinct from a
    # JSON-RPC-level `error` object. Surface this before any caller tries to
    # json.loads() that text as a second parse — otherwise a real failure
    # (e.g. "Job not found") is misreported as a parse error.
    if result.get("isError"):
        content = result.get("content") or []
        message = content[0].get("text") if content and "text" in content[0] else str(result)
        raise SuperDocsRpcError(
            what=f"SuperDocs tool '{tool_name}' reported an error",
            likely_cause=message,
            next_action="inspect the arguments/session/job id sent to this tool call; if the message names a missing job or session, it may have expired or already completed",
        )

    return result


def _parse_tool_result_text(result: dict[str, Any], tool_name: str) -> dict[str, Any]:
    """Parse the SECOND, independent JSON document inside `result.content[0].text`.

    This is the parse most likely to fail in practice: the outer envelope is
    well-formed JSON-RPC, but the inner text is itself a JSON string produced
    by the tool implementation and can be truncated or malformed.
    """

    content = result.get("content") or []
    if not content or "text" not in content[0]:
        raise SuperDocsParseError(
            what=f"SuperDocs '{tool_name}' response had no content[0].text to parse",
            likely_cause="unexpected response shape from SuperDocs — the tool schema may have changed",
            next_action="inspect the raw envelope and compare against the documented tool schema",
        )
    text = content[0]["text"]
    try:
        return json.loads(text, strict=False)
    except ValueError as exc:
        raise SuperDocsParseError(
            what=f"could not parse pending_changes/result JSON from SuperDocs '{tool_name}' response",
            likely_cause="SuperDocs returned non-JSON or truncated content in content[0].text",
            next_action="retry the call (get_job for polling); if persistent, inspect the job via the SuperDocs dashboard",
        ) from exc


@dataclass(frozen=True)
class UploadResult:
    session_id: str
    filename: str
    chunks_count: Optional[int]
    version_id: Optional[str]


async def upload_document(
    client: httpx.AsyncClient,
    filename: str,
    content_bytes: bytes,
    session_id: str,
) -> UploadResult:
    """Upload a contract document into a new or existing SuperDocs session."""

    file_base64 = base64.b64encode(content_bytes).decode("ascii")
    result = await _call_tool(
        client,
        "upload_document_base64",
        {
            "filename": filename,
            "file_base64": file_base64,
            "session_id": session_id,
            "return_html": False,
        },
    )
    parsed = _parse_tool_result_text(result, "upload_document_base64")
    return UploadResult(
        session_id=parsed.get("session_id", session_id),
        filename=parsed.get("filename", filename),
        chunks_count=parsed.get("chunks_count"),
        version_id=parsed.get("version_id"),
    )


async def propose_change(
    client: httpx.AsyncClient,
    session_id: str,
    instruction: str,
) -> str:
    """Send a tightly-scoped edit instruction and return the async job_id.

    Always uses `approval_mode="ask_every_time"` so every proposed change
    requires an explicit `approve_change` call — this app never auto-applies
    a SuperDocs edit.
    """

    result = await _call_tool(
        client,
        "chat_async",
        {
            "session_id": session_id,
            "message": instruction,
            "approval_mode": "ask_every_time",
        },
    )
    parsed = _parse_tool_result_text(result, "chat_async")
    job_id = parsed.get("job_id")
    if not job_id:
        raise SuperDocsParseError(
            what="chat_async response had no job_id",
            likely_cause="unexpected response shape from SuperDocs chat_async",
            next_action="inspect the raw response and compare against the documented tool schema",
        )
    return job_id


@dataclass(frozen=True)
class ProposedChange:
    change_id: str
    operation: str
    chunk_id: str
    old_html: Optional[str]
    new_html: Optional[str]
    ai_explanation: Optional[str]


@dataclass(frozen=True)
class JobStatus:
    job_id: str
    status: str
    pending_changes: list[ProposedChange] = field(default_factory=list)
    response_text: Optional[str] = None
    document_changes: Optional[dict[str, Any]] = None
    cumulative_tokens: Optional[int] = None


async def poll_job(client: httpx.AsyncClient, job_id: str) -> JobStatus:
    """Fetch a chat_async job's current state, including any pending changes.

    Always requests non-compact (`compact=False`) because `pending_changes`
    is only populated in the metadata when the full (non-compact) job body
    is returned — verified against the live API, which returns
    `pending_changes: null` in compact mode even once `awaiting_approval`.
    """

    result = await _call_tool(client, "get_job", {"job_id": job_id, "compact": False})
    parsed = _parse_tool_result_text(result, "get_job")

    status = parsed.get("status")
    if not status:
        raise SuperDocsParseError(
            what="get_job response had no status field",
            likely_cause="unexpected response shape from SuperDocs get_job",
            next_action="inspect the raw response and compare against the documented tool schema",
        )

    metadata = parsed.get("metadata") or {}
    raw_pending = metadata.get("pending_changes") or []
    pending_changes = [
        ProposedChange(
            change_id=item["change_id"],
            operation=item.get("operation", "unknown"),
            chunk_id=item.get("chunk_id", ""),
            old_html=item.get("old_html"),
            new_html=item.get("new_html"),
            ai_explanation=item.get("ai_explanation"),
        )
        for item in raw_pending
    ]

    job_result = parsed.get("result") or {}
    return JobStatus(
        job_id=parsed.get("job_id", job_id),
        status=status,
        pending_changes=pending_changes,
        response_text=job_result.get("response"),
        document_changes=job_result.get("document_changes"),
        cumulative_tokens=metadata.get("cumulative_tokens"),
    )


@dataclass(frozen=True)
class ApprovalResult:
    status: str
    batch_complete: bool


async def approve_change(
    client: httpx.AsyncClient,
    session_id: str,
    job_id: str,
    change_id: str,
    approved: bool,
    feedback: Optional[str] = None,
) -> ApprovalResult:
    """Approve or reject one pending change (never a bulk auto-approve)."""

    arguments: dict[str, Any] = {
        "session_id": session_id,
        "job_id": job_id,
        "change_id": change_id,
        "approved": approved,
    }
    if feedback is not None:
        arguments["feedback"] = feedback

    result = await _call_tool(client, "approve_change", arguments)
    parsed = _parse_tool_result_text(result, "approve_change")
    return ApprovalResult(
        status=parsed.get("status", "unknown"),
        batch_complete=bool(parsed.get("batch_complete", False)),
    )


async def export_document(
    client: httpx.AsyncClient,
    session_id: str,
    export_format: str = "markdown",
) -> str:
    """Export the session's current document and return the rendered text.

    `export_format` in {"markdown", "html", "txt"} returns inline text
    directly in `content[0].text`. Binary formats (docx/pdf) are out of
    scope for this app's export path — see README for the
    `request_download_url` alternative for those formats.
    """

    if export_format not in {"markdown", "html", "txt"}:
        raise SuperDocsError(
            what=f"export_format '{export_format}' is not supported by this client",
            likely_cause="only text-based formats (markdown/html/txt) are read inline; docx/pdf require request_download_url",
            next_action="use export_format='markdown' or extend this client to support request_download_url for binary formats",
        )

    result = await _call_tool(
        client,
        "export_document",
        {"session_id": session_id, "format": export_format},
    )
    content = result.get("content") or []
    if not content or "text" not in content[0]:
        raise SuperDocsParseError(
            what="export_document response had no content[0].text",
            likely_cause="unexpected response shape from SuperDocs export_document",
            next_action="inspect the raw response and compare against the documented tool schema",
        )
    return content[0]["text"]


async def get_account_status(client: httpx.AsyncClient) -> dict[str, Any]:
    """Return the SuperDocs account/quota status — used for a startup health check."""

    result = await _call_tool(client, "get_account_status", {})
    return _parse_tool_result_text(result, "get_account_status")
