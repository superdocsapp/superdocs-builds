from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LiveSuperDocsError(RuntimeError):
    pass


class LiveRemoteOutcomeUnknown(LiveSuperDocsError):
    """A timeout means reconcile the same operation/session before retrying."""


class LiveSuperDocsREST:
    """REST adapter for the documented SuperDocs upload/chat/approve/export contract."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None, timeout: float = 60.0) -> None:
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise LiveSuperDocsError("SUPERDOCS_API_KEY is required for live mode")
        self.base_url = (base_url or os.environ.get("SUPERDOCS_API_URL", "https://api.superdocs.app")).rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None, operation_key: str | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if operation_key:
            headers["Idempotency-Key"] = operation_key
        request = Request(self.base_url + path, method=method, headers=headers, data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (TimeoutError, URLError) as error:
            raise LiveRemoteOutcomeUnknown(f"remote outcome unknown for {operation_key or path}; reconcile before retrying") from error
        except HTTPError as error:
            detail = error.read().decode(errors="replace")
            raise LiveSuperDocsError(f"SuperDocs HTTP {error.code}: {detail}") from error

    def chat(self, session_id: str, message: str, document_html: str | None = None, operation_key: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"session_id": session_id, "message": message}
        if document_html is not None:
            payload["document_html"] = document_html
        return self.request("POST", "/v1/chat", payload, operation_key)

    def approve(self, session_id: str, job_id: str, approved: bool, change_id: str | None = None, feedback: str | None = None, operation_key: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"job_id": job_id, "approved": approved}
        if change_id is not None:
            payload["change_id"] = change_id
        if feedback is not None:
            payload["feedback"] = feedback
        return self.request("POST", f"/v1/chat/{session_id}/approve", payload, operation_key)

    def export(self, session_id: str, format_name: str = "docx", operation_key: str | None = None) -> dict[str, Any]:
        return self.request("POST", "/v1/documents/export", {"session_id": session_id, "format": format_name}, operation_key)


class LiveSuperDocsMCP:
    """Minimal Streamable HTTP MCP client for calling the live server's named tools."""

    def __init__(self, api_key: str | None = None, endpoint: str | None = None, timeout: float = 60.0) -> None:
        self.api_key = api_key or os.environ.get("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise LiveSuperDocsError("SUPERDOCS_API_KEY is required for live mode")
        self.endpoint = endpoint or os.environ.get("SUPERDOCS_MCP_URL", "https://api.superdocs.app/mcp/")
        self.timeout = timeout

    def call_tool(self, name: str, arguments: dict[str, Any], request_id: int = 1) -> dict[str, Any]:
        body = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
        request = Request(self.endpoint, method="POST", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}, data=json.dumps(body).encode())
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode()
        except (TimeoutError, URLError) as error:
            raise LiveRemoteOutcomeUnknown(f"MCP outcome unknown for tool {name}; reconcile before retrying") from error
        try:
            if raw.startswith("data:"):
                raw = next(line[5:].strip() for line in raw.splitlines() if line.startswith("data:"))
            return json.loads(raw)
        except (StopIteration, json.JSONDecodeError) as error:
            raise LiveSuperDocsError("live MCP response was not valid JSON or SSE JSON") from error
