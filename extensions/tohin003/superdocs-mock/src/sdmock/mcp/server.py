"""A mock of the SuperDocs MCP server, served from the pinned surface and the cassettes.

Why this exists at all: SuperDocs' MCP tools and prompts are served **live from the
backend** -- the Claude Code plugin carries only a manifest -- so an agent integration has
no local artifact to test against and no way to run CI without a key. That is the same
problem the REST mock solves, one layer up.

Two sources, deliberately separated:

* `initialize`, `tools/list` and `prompts/list` answer from `spec/mcp-tools.json`, the
  surface captured in Phase 1. The mock therefore advertises exactly the 38 tools and 4
  prompts the live server advertised, rather than a retyped subset that would quietly
  drift.

* `tools/call` answers from the cassettes. If the scenario recorded that tool over MCP,
  that recording is served verbatim. Otherwise the call is resolved through the **same**
  `Library` the REST app uses (D7), so `chat` over MCP and `POST /v1/chat` over REST
  return the same underlying data. That shared path is what makes the contract suite's
  parity test meaningful instead of circular.

A tool the mock cannot answer returns an MCP error saying so. It never fabricates a tool
result -- an agent that acts on invented output is worse off than one that got an error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import mutants
from ..cassette import Cassette, dumps
from ..replay import InteractionNotFound, Library, ScenarioNotFound

from ..paths import spec_dir

# Tool -> the REST operation it stands on. Taken from the MCP tool reference; this is the
# bridge that lets one cassette serve both transports.
TOOL_ROUTES: dict[str, tuple[str, str]] = {
    "chat": ("POST", "/v1/chat"),
    "chat_async": ("POST", "/v1/chat/async"),
    "approve_change": ("POST", "/v1/chat/{session_id}/approve"),
    "continue_chat": ("POST", "/v1/chat/{session_id}/continue"),
    "get_job": ("GET", "/v1/jobs/{job_id}"),
    "list_jobs": ("GET", "/v1/jobs"),
    "cancel_job": ("POST", "/v1/jobs/{job_id}/cancel"),
    "get_session_jobs": ("GET", "/v1/sessions/{session_id}/jobs"),
    "get_session_history": ("GET", "/v1/sessions/{session_id}/history"),
    "list_sessions": ("GET", "/v1/sessions"),
    "export_document": ("POST", "/v1/documents/export"),
    "request_download_url": ("POST", "/v1/downloads"),
    "request_upload_url": ("POST", "/v1/uploads"),
    "process_uploaded_document": ("POST", "/v1/uploads/{upload_id}/process"),
    "upload_document_base64": ("POST", "/v1/documents/upload-base64"),
    "upload_attachment_base64": ("POST", "/v1/attachments/upload-base64"),
    "upload_template_base64": ("POST", "/v1/templates/upload-base64"),
    "list_documents": ("GET", "/v1/documents"),
    "get_document_detail": ("GET", "/v1/documents/{document_id}"),
    "list_session_documents": ("GET", "/v1/sessions/{session_id}/documents"),
    "list_user_templates": ("GET", "/v1/templates"),
    "get_account_status": ("GET", "/v1/agents/whoami"),
    "request_limit_increase": ("POST", "/v1/limits/increase-request"),
    "get_attachment_status": ("GET", "/v1/attachments/status/{session_id}"),
    "health": ("GET", "/health"),
}

# Path parameters, and which tool argument fills each one.
PARAM_SOURCES = {
    "{session_id}": "session_id",
    "{job_id}": "job_id",
    "{document_id}": "document_id",
    "{upload_id}": "upload_id",
    "{attachment_id}": "attachment_id",
}

PROTOCOL_FALLBACK = "2025-06-18"


class MCPServer:
    def __init__(self, library: Library, pin_path: Path | None = None) -> None:
        self.library = library
        self.session_id = "sdmock-mcp-session"
        pin = pin_path or (spec_dir() / "mcp-tools.json")
        raw = json.loads(pin.read_text(encoding="utf-8"))
        self._initialize: dict[str, Any] = raw.get("initialize", {})
        self._tools: list[dict[str, Any]] = raw.get("tools", [])
        self._prompts: list[dict[str, Any]] = raw.get("prompts", [])

    # ---------------------------------------------------------------- dispatch

    def handle(
        self, payload: dict[str, Any], *, scenario: str, run: str = "default"
    ) -> dict[str, Any] | None:
        method = payload.get("method", "")
        rpc_id = payload.get("id")
        params = payload.get("params") or {}

        if method.startswith("notifications/"):
            return None  # acknowledged with a bare 202, as Streamable HTTP expects
        if rpc_id is None:
            return None

        try:
            if method == "initialize":
                return self._ok(rpc_id, self._initialize_result(params))
            if method == "ping":
                return self._ok(rpc_id, {})
            if method == "tools/list":
                tools = self._tools
                mutant = mutants.active()
                if mutant is not None and mutant.tools is not None:
                    tools = mutant.tools(tools)
                return self._ok(rpc_id, {"tools": tools})
            if method == "prompts/list":
                return self._ok(rpc_id, {"prompts": self._prompts})
            if method == "resources/list":
                return self._ok(rpc_id, {"resources": []})
            if method == "tools/call":
                result = self._call(params, scenario, run)
                mutant = mutants.active()
                if mutant is not None and mutant.mcp_result is not None:
                    result = mutant.mcp_result(result)
                return self._ok(rpc_id, result)
        except ScenarioNotFound as exc:
            return self._error(
                rpc_id, -32602,
                f"Unknown scenario {exc.requested!r}. Available: "
                + ", ".join(exc.available),
            )

        return self._error(
            rpc_id, -32601,
            f"Method {method!r} is not implemented by this mock. Implemented: "
            "initialize, ping, tools/list, prompts/list, resources/list, tools/call.",
        )

    # ---------------------------------------------------------------- results

    def _initialize_result(self, params: dict[str, Any]) -> dict[str, Any]:
        result = dict(self._initialize)
        # Echo the client's protocol version when we recorded one at least as new,
        # which is what a well-behaved server does.
        requested = params.get("protocolVersion")
        if requested and requested <= result.get("protocolVersion", PROTOCOL_FALLBACK):
            result["protocolVersion"] = requested
        server = dict(result.get("serverInfo") or {})
        server["name"] = f"{server.get('name', 'SuperDocs')} (sdmock replay)"
        result["serverInfo"] = server
        return result

    def _call(self, params: dict[str, Any], scenario: str, run: str) -> dict[str, Any]:
        name = params.get("name", "")
        arguments = params.get("arguments") or {}

        recorded = self._recorded_tool_call(scenario, name)
        if recorded is not None:
            return recorded

        route = TOOL_ROUTES.get(name)
        if route is None:
            known = ", ".join(sorted(t["name"] for t in self._tools))
            return self._tool_error(
                f"Tool {name!r} is advertised by SuperDocs but is not backed by any "
                f"cassette in this mock, and it has no REST equivalent wired up. "
                f"This mock never invents a tool result. Tools it can answer: "
                f"{', '.join(sorted(TOOL_ROUTES))}."
                + ("" if name in known else " (Tool name not in the pinned surface.)")
            )

        method, template = route
        path = template
        for placeholder, argument in PARAM_SOURCES.items():
            if placeholder in path:
                path = path.replace(placeholder, str(arguments.get(argument, "unknown")))

        try:
            resolution = self.library.resolve(method, path, scenario=scenario, run=run)
        except InteractionNotFound as exc:
            return self._tool_error(
                f"Scenario {scenario!r} has no recording behind {name!r} "
                f"({exc.method} {exc.template}). Switch scenarios with the "
                f"X-Mock-Scenario header, or record it. Recorded here: "
                + ", ".join(exc.available)
            )

        response = resolution.interaction.response
        body = response.json_body
        if body is None:
            body = {"status": response.status, "body": response.text_body or "<binary>"}

        payload = {
            "content": [{"type": "text", "text": dumps(body)}],
            "structuredContent": body if isinstance(body, dict) else {"result": body},
            "isError": response.status >= 400,
        }
        if resolution.cassette.synthesised:
            payload["_meta"] = {"sdmock/synthesised": True}
        return payload

    def _recorded_tool_call(self, scenario: str, name: str) -> dict[str, Any] | None:
        """Serve a tool call that was itself recorded over MCP, verbatim."""
        cassette: Cassette | None = self.library.cassettes.get(scenario)
        if cassette is None:
            raise ScenarioNotFound(scenario, self.library.scenarios)
        for interaction in cassette.interactions:
            if interaction.transport != "mcp":
                continue
            body = interaction.request.json_body or {}
            if body.get("method") != "tools/call":
                continue
            if ((body.get("params") or {}).get("name")) != name:
                continue
            recorded = (interaction.response.json_body or {}).get("result")
            if isinstance(recorded, dict):
                return recorded
        return None

    def _tool_error(self, message: str) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": message}], "isError": True}

    # ---------------------------------------------------------------- envelopes

    @staticmethod
    def _ok(rpc_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

    @staticmethod
    def _error(rpc_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": code, "message": message}}
