"""MCP-over-HTTP transport for the live SuperDocs service.

Speaks JSON-RPC over the streamable-HTTP MCP binding: `initialize`, then
`notifications/initialized`, then `tools/call`. Responses arrive either as plain
JSON or as an SSE stream depending on the server; both are handled.

The key is read from .env through `config.get` and is never logged, printed,
echoed into an error message, or written to any artefact. Errors quote the tool
name and the server's message only.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

import config
from superdocs.client import SuperDocsError

ENDPOINT = "https://api.superdocs.app/mcp"
PROTOCOL_VERSION = "2025-06-18"


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class MCPHttpTransport:
    """One live session against SuperDocs. Not thread-safe by design: the meter
    probe needs exactly one call in flight at a time."""

    def __init__(self, endpoint: str = ENDPOINT, api_key: str | None = None,
                 timeout: int = 240):
        self.endpoint = endpoint
        self._key = api_key or config.get("SUPERDOCS_SK")
        if not self._key:
            raise SuperDocsError("SUPERDOCS_SK is not set; no live call is "
                                 "possible and nothing will be faked")
        # 240s: the 'pro' model tier at 'deep' thinking exceeded a 90s read
        # timeout on a full correction payload. 'core'/'balanced' returns well
        # inside it and is the tier the measurement uses.
        self.timeout = timeout
        self.session_id: str | None = None
        self._next_id = 0
        self._initialized = False
        self.last_raw: dict | None = None

    # --- JSON-RPC plumbing ------------------------------------------------

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._key}",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload: dict, expect_response: bool = True):
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=body,
                                         headers=self._headers())
        try:
            with urllib.request.urlopen(request, timeout=self.timeout,
                                        context=_ssl_context()) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                raw = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise SuperDocsError(
                f"HTTP {exc.code} from SuperDocs: {detail}",
                billed=False, retryable=exc.code in (429, 500, 502, 503, 504)
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SuperDocsError(f"transport failure: {exc}", billed=False,
                                 retryable=True) from exc

        if not expect_response:
            return None
        return _parse_body(raw, content_type)

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        message = self._post(payload)
        if message is None:
            raise SuperDocsError(f"{method}: empty response from server")
        if "error" in message:
            error = message["error"]
            raise SuperDocsError(
                f"{method} failed: {error.get('message', error)}",
                billed=False, tool=method,
                retryable=error.get("code") in (-32000, -32603))
        return message.get("result", {})

    # --- MCP lifecycle ----------------------------------------------------

    def initialize(self) -> dict:
        result = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "superdocs-editor-agent", "version": "0.1"},
        })
        self._next_id += 1
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"},
                   expect_response=False)
        self._initialized = True
        return result

    def list_tools(self) -> list[dict]:
        if not self._initialized:
            self.initialize()
        return self._rpc("tools/list", {}).get("tools", [])

    # --- Transport protocol used by SuperDocsClient -----------------------

    def call(self, tool: str, params: dict) -> dict:
        if not self._initialized:
            self.initialize()
        result = self._rpc("tools/call", {"name": tool, "arguments": params})
        self.last_raw = result
        if result.get("isError"):
            return {"error": _text_of(result) or "tool reported an error"}
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        text = _text_of(result)
        if text:
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
                return {"result": parsed}
            except json.JSONDecodeError:
                return {"result": text}
        return {}


def _text_of(result: dict) -> str:
    parts = [block.get("text", "") for block in result.get("content", [])
             if isinstance(block, dict) and block.get("type") == "text"]
    return "\n".join(p for p in parts if p).strip()


def _parse_body(raw: str, content_type: str) -> dict | None:
    """Handle both a plain JSON body and an SSE stream of JSON-RPC messages."""
    raw = raw.strip()
    if not raw:
        return None
    if "text/event-stream" in content_type or raw.startswith("event:"):
        last = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if chunk:
                    try:
                        last = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
        return last
    return json.loads(raw)
