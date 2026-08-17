"""Small adapter around the SuperDocs MCP document-operation tools.

The adapter does not implement rendering or editing itself.  A host-provided
MCP invoker performs each named SuperDocs operation.  This makes it easy to
unit test with a recording invoker while production uses the configured
SuperDocs MCP connection.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


McpInvoker = Callable[[str, dict[str, Any]], Any]


def parse_json_value(value: Any) -> Any:
    """Parse a JSON-encoded string once; leave decoded values untouched."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def normalized_response(response: Any) -> dict[str, Any]:
    """Normalise MCP output and handle JSON-encoded proposed-change fields."""
    parsed = parse_json_value(response)
    if not isinstance(parsed, Mapping):
        raise TypeError("SuperDocs MCP response must be an object or JSON object string")
    result = dict(parsed)
    for field in ("proposed_change", "change", "result", "data"):
        if field in result:
            result[field] = parse_json_value(result[field])
    return result


def _identifier(response: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = response.get(name)
        if value:
            return str(value)
    raise KeyError(f"SuperDocs response did not include one of: {', '.join(names)}")


@dataclass(frozen=True)
class UploadedDocument:
    """Stable references returned by an upload operation."""

    document_id: str
    session_id: str | None
    version: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class PendingChange:
    """A proposed async edit that must be approved by a human."""

    change_id: str
    status: str
    proposed_change: Any
    raw: dict[str, Any]


class SuperDocsClient:
    """Call SuperDocs MCP tools through a host-supplied invoker."""

    def __init__(self, invoke: McpInvoker) -> None:
        self._invoke = invoke

    def upload_html(self, html: str, *, filename: str) -> UploadedDocument:
        """Encode HTML then send it to SuperDocs' upload_document_base64 tool."""
        payload = base64.b64encode(html.encode("utf-8")).decode("ascii")
        response = normalized_response(
            self._invoke(
                "upload_document_base64",
                {
                    "filename": filename,
                    "content_base64": payload,
                    "mime_type": "text/html",
                },
            )
        )
        return UploadedDocument(
            document_id=_identifier(response, "document_id", "documentId", "id"),
            session_id=(str(response["session_id"]) if response.get("session_id") else None),
            version=(str(response["version"]) if response.get("version") is not None else None),
            raw=response,
        )

    def request_async_edit(self, *, session_id: str, instruction: str) -> PendingChange:
        """Request an edit but never apply it automatically."""
        response = normalized_response(
            self._invoke("chat_async", {"session_id": session_id, "message": instruction})
        )
        change = response.get("proposed_change", response.get("change"))
        return PendingChange(
            change_id=_identifier(response, "change_id", "changeId", "job_id", "jobId"),
            status=str(response.get("status", "awaiting_approval")),
            proposed_change=change,
            raw=response,
        )

    def approve_change(self, *, session_id: str, change_id: str) -> dict[str, Any]:
        """Apply one explicitly selected proposed change after human approval."""
        return normalized_response(
            self._invoke("approve_change", {"session_id": session_id, "change_id": change_id})
        )

    def export_pdf(self, *, document_id: str, session_id: str | None = None) -> dict[str, Any]:
        """Request the final PDF from SuperDocs; this is the workflow endpoint."""
        arguments: dict[str, Any] = {"document_id": document_id, "format": "pdf"}
        if session_id:
            arguments["session_id"] = session_id
        return normalized_response(self._invoke("export_document", arguments))


class RecordingMcpInvoker:
    """Offline test double that records calls and yields predefined responses."""

    def __init__(self, responses: Mapping[str, Any]) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((tool_name, arguments))
        return self.responses[tool_name]
