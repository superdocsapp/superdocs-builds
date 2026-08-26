"""Thin wrapper over the SuperDocs MCP client used by every other module."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import AsyncExitStack

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)

MCP_URL = "https://api.superdocs.app/mcp/"

# httpx2.AsyncClient defaults to a 5-second timeout, which would silently cancel
# a legitimate multi-minute SuperDocs call before our own generous ceiling ever
# applies. Override it here so the transport layer imposes no timeout of its own;
# _call_tool's own ceiling is the single place a timeout is enforced.
_TRANSPORT_TIMEOUT = httpx2.Timeout(None)

# SuperDocs calls legitimately run 30 seconds to several minutes with no visible
# progress; this is a safety net against a genuinely hung call, not a normal
# operating limit. It must never be tight enough to cancel a working call.
DEFAULT_CALL_TIMEOUT_SECONDS = 900.0

# Transport-layer failures only — a connection that was never established or
# broke mid-flight. A slow-but-live response is never one of these, so it is
# never retried; only a demonstrable transport failure is.
_TRANSPORT_ERRORS = (
    httpx2.TransportError,
    httpx2.ConnectError,
    httpx2.ReadError,
    httpx2.WriteError,
    httpx2.RemoteProtocolError,
    ConnectionError,
)
_TRANSPORT_RETRY_ATTEMPTS = 3
_TRANSPORT_RETRY_BACKOFF_SECONDS = 2.0


class SuperDocsClientError(RuntimeError):
    """Raised with the cause and the fix, never just a status code."""


def _api_key() -> str:
    key = os.environ.get("SUPERDOCS_API_KEY")
    if not key:
        raise SuperDocsClientError(
            "SUPERDOCS_API_KEY is not set. Fix: copy .env.example to .env and set "
            "SUPERDOCS_API_KEY to your SuperDocs key (starts with 'sk_'), or export it "
            "in your shell before running."
        )
    return key


class SuperDocsClient:
    """Connects to the SuperDocs MCP server over streamable HTTP with bearer auth.

    Exposes exactly four operations as thin methods: upload, chat, approve, export.
    Everything else on the SuperDocs MCP surface is optional depth not built here.
    """

    def __init__(self, url: str = MCP_URL, call_timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS):
        self._url = url
        self._call_timeout = call_timeout
        self._exit_stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> "SuperDocsClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def connect(self) -> None:
        api_key = _api_key()
        headers = {"Authorization": f"Bearer {api_key}"}
        self._exit_stack = AsyncExitStack()
        http_client = httpx2.AsyncClient(headers=headers, timeout=_TRANSPORT_TIMEOUT)
        await self._exit_stack.enter_async_context(http_client)
        read, write = await self._exit_stack.enter_async_context(
            streamable_http_client(self._url, http_client=http_client)
        )
        # read_timeout_seconds=None: the session layer imposes no timeout of its
        # own either — _call_tool's ceiling is the single enforced timeout.
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write, read_timeout_seconds=None)
        )
        await session.initialize()
        self._session = session

    async def close(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._exit_stack = None
        self._session = None

    async def _call_tool(self, name: str, arguments: dict) -> dict:
        if self._session is None:
            raise SuperDocsClientError(
                f"Cannot call '{name}': not connected. Fix: use "
                "'async with SuperDocsClient() as client:' or call connect() first."
            )

        attempt = 0
        while True:
            attempt += 1
            started = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    self._session.call_tool(name, arguments), timeout=self._call_timeout
                )
            except asyncio.TimeoutError as exc:
                elapsed = time.monotonic() - started
                raise SuperDocsClientError(
                    f"SuperDocs tool '{name}' exceeded the {self._call_timeout:.0f}s ceiling "
                    f"after {elapsed:.0f}s. This is a safety net against a hung call, not a "
                    "normal failure — SuperDocs calls legitimately run for minutes. Fix: check "
                    "the session/job state on SuperDocs before retrying; the original call may "
                    "still be running server-side, so do not blindly re-call."
                ) from exc
            except _TRANSPORT_ERRORS as exc:
                elapsed = time.monotonic() - started
                logger.warning(
                    "SuperDocs tool '%s' transport failure after %.1fs (attempt %d/%d): %s",
                    name, elapsed, attempt, _TRANSPORT_RETRY_ATTEMPTS, exc,
                )
                if attempt >= _TRANSPORT_RETRY_ATTEMPTS:
                    raise SuperDocsClientError(
                        f"SuperDocs tool '{name}' failed after {attempt} transport-level "
                        f"attempts: {exc}. Fix: check network connectivity to {self._url} and "
                        "that the SuperDocs MCP server is reachable, then retry."
                    ) from exc
                await asyncio.sleep(_TRANSPORT_RETRY_BACKOFF_SECONDS * attempt)
                continue
            else:
                elapsed = time.monotonic() - started
                logger.info("SuperDocs tool '%s' completed in %.1fs", name, elapsed)
                break

        is_error = getattr(result, "is_error", getattr(result, "isError", False))
        if is_error:
            detail = _first_text(result.content) or "no error detail returned"
            raise SuperDocsClientError(f"SuperDocs tool '{name}' returned an error: {detail}")
        structured_content = getattr(
            result, "structured_content", getattr(result, "structuredContent", None)
        )
        if structured_content is not None:
            return structured_content
        text = _first_text(result.content)
        if text is None:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    async def upload(
        self, filename: str, file_base64: str, session_id: str | None = None, return_html: bool = False
    ) -> dict:
        """Upload a document as the active editable document for a session."""
        arguments = {"filename": filename, "file_base64": file_base64, "return_html": return_html}
        if session_id is not None:
            arguments["session_id"] = session_id
        return await self._call_tool("upload_document_base64", arguments)

    async def export(
        self,
        session_id: str | None = None,
        html: str | None = None,
        format: str = "docx",
        options: dict | None = None,
        filename: str | None = None,
    ) -> dict:
        """Export the current document as docx, pdf, html, markdown, or txt."""
        if session_id is None and html is None:
            raise SuperDocsClientError(
                "export requires either session_id or html. Fix: pass the session_id "
                "whose document you want exported, or pass html directly."
            )
        arguments: dict = {"format": format}
        if session_id is not None:
            arguments["session_id"] = session_id
        if html is not None:
            arguments["html"] = html
        if options is not None:
            arguments["options"] = options
        if filename is not None:
            arguments["filename"] = filename
        return await self._call_tool("export_document", arguments)

    async def chat(
        self,
        message: str,
        session_id: str,
        document_html: str | None = None,
        approval_mode: str | None = None,
        response_mode: str | None = None,
        **extra,
    ) -> dict:
        """Send a synchronous chat instruction to edit, draft, or restructure a document."""
        arguments: dict = {"message": message, "session_id": session_id, **extra}
        if document_html is not None:
            arguments["document_html"] = document_html
        if approval_mode is not None:
            arguments["approval_mode"] = approval_mode
        if response_mode is not None:
            arguments["response_mode"] = response_mode
        return await self._call_tool("chat", arguments)

    async def approve(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        change_id: str | None = None,
        feedback: str | None = None,
        changes: list[dict] | None = None,
    ) -> dict:
        """Approve or deny AI-proposed changes from a chat_async job, one-by-one or in batch."""
        arguments: dict = {"session_id": session_id, "job_id": job_id, "approved": approved}
        if change_id is not None:
            arguments["change_id"] = change_id
        if feedback is not None:
            arguments["feedback"] = feedback
        if changes is not None:
            arguments["changes"] = changes
        return await self._call_tool("approve_change", arguments)


def _first_text(content) -> str | None:
    for block in content or []:
        text = getattr(block, "text", None)
        if text is not None:
            return text
    return None


_REQUIRED_CHANGE_FIELDS = ("change_id", "operation", "chunk_id", "old_html", "new_html")


def parse_proposed_changes(response) -> list[dict]:
    """Extract the list of proposed changes from a SuperDocs chat/get_job response.

    The single place this codebase unwraps a proposed-change payload. SuperDocs
    hands the same underlying data back in two shapes, and a caller should never
    have to know which one they got:

    - Already-an-object: `metadata.pending_changes` (or `pending_changes`, or
      `document_changes.pending_changes`) is already a list of change dicts.
      No parsing needed — this is the final result.
    - Double-encoded: an `intermediate_responses` entry with
      `type == "proposed_change_batch"` whose `content` field is a JSON-encoded
      STRING, not an object. It must be parsed once (a second parse relative to
      the outer response, which the MCP client already parsed) to reach
      `{"type", "batch_id", "batch_total", "changes": [...]}`. A bare JSON
      string or an already-parsed batch dict, passed directly, are also accepted.

    Raises SuperDocsClientError — never returns None — when the payload is
    neither shape, or when a change is missing a required field, rather than
    handing back a change whose fields silently read as undefined.
    """
    changes = _locate_changes(response)
    for change in changes:
        missing = [field for field in _REQUIRED_CHANGE_FIELDS if field not in change]
        if missing:
            raise SuperDocsClientError(
                f"Proposed change {change.get('change_id', '<unknown>')!r} is missing "
                f"required field(s) {missing}. Fix: this is not a valid SuperDocs "
                "proposed-change payload — check the response was passed to "
                "parse_proposed_changes unmodified, not partially unwrapped first."
            )
    return changes


def _locate_changes(response) -> list[dict]:
    if isinstance(response, str):
        return _changes_from_batch(_parse_json_string(response, context="response"))

    if not isinstance(response, dict):
        raise SuperDocsClientError(
            "parse_proposed_changes expected a dict or a JSON-encoded string, got "
            f"{type(response).__name__}. Fix: pass the raw chat/get_job response, or "
            "an intermediate_responses[].content string, unmodified."
        )

    if isinstance(response.get("changes"), list):
        return response["changes"]

    metadata = response.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    document_changes = response.get("document_changes")
    document_changes = document_changes if isinstance(document_changes, dict) else {}

    for pending in (
        response.get("pending_changes"),
        metadata.get("pending_changes"),
        document_changes.get("pending_changes"),
    ):
        if isinstance(pending, list) and pending:
            return pending

    intermediate = response.get("intermediate_responses") or metadata.get("intermediate_responses")
    if isinstance(intermediate, list):
        for entry in intermediate:
            if isinstance(entry, dict) and entry.get("type") == "proposed_change_batch":
                content = entry.get("content")
                if isinstance(content, str):
                    return _changes_from_batch(
                        _parse_json_string(content, context="intermediate_responses[].content")
                    )
                if isinstance(content, dict):
                    return _changes_from_batch(content)

    raise SuperDocsClientError(
        "No proposed changes found in this response. Fix: pass the response from a "
        "chat/get_job call made with approval_mode='ask_every_time' while the job is "
        "awaiting_approval — look for metadata.pending_changes or an "
        "intermediate_responses entry of type 'proposed_change_batch'."
    )


def _parse_json_string(text: str, context: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SuperDocsClientError(
            f"Could not parse {context} as JSON: {exc}. Fix: this field is documented "
            "as a JSON-encoded string — if SuperDocs changed that, this helper needs updating."
        ) from exc


def _changes_from_batch(batch: dict) -> list[dict]:
    if not isinstance(batch, dict) or "changes" not in batch:
        raise SuperDocsClientError(
            f"Parsed proposed-change payload has no 'changes' field: {batch!r}. Fix: "
            "this is not the expected {'type', 'batch_id', 'batch_total', 'changes'} shape."
        )
    changes = batch["changes"]
    if not isinstance(changes, list):
        raise SuperDocsClientError(
            f"Proposed-change payload's 'changes' field is not a list: {type(changes).__name__}."
        )
    return changes
