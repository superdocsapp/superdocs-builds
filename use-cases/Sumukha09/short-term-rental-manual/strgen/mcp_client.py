

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .errors import SuperDocsError

DEFAULT_ENDPOINT = "https://api.superdocs.app/mcp/"
PROTOCOL_VERSION = "2025-03-26"


class SuperDocsMCP:
    def __init__(self, api_key: str | None = None,
                 endpoint: str = DEFAULT_ENDPOINT,
                 timeout: int = 240,
                 quiet: bool = False):
        if not api_key:
            raise SuperDocsError(
                "SuperDocs API key missing. Set SUPERDOCS_API_KEY or add it to .env"
            )
        self.endpoint = endpoint
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.quiet = quiet
        self.session_id: str | None = None
        self._next_id = 0

    # ------------------------------------------------------------------ rpc

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
        return headers

    def _parse_body(self, raw: bytes, content_type: str) -> list[dict]:
        text = raw.decode("utf-8", errors="replace")
        if not text.strip():
            return []  # e.g. accepted notifications answer 200 with empty body
        if "text/event-stream" in content_type:
            messages: list[dict] = []
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk and chunk != "[DONE]":
                        try:
                            messages.append(json.loads(chunk))
                        except json.JSONDecodeError:
                            continue
            return messages
        try:
            return [json.loads(text)]
        except json.JSONDecodeError as exc:
            raise SuperDocsError(f"Unparseable MCP response: {text[:200]}") from exc

    def _post_once(self, payload: dict) -> tuple[list[dict], dict[str, str]]:
        req = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return self._parse_body(
                    resp.read(), resp.headers.get("Content-Type", "")), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise SuperDocsError(f"HTTP {exc.code} from SuperDocs: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SuperDocsError(f"Cannot reach SuperDocs ({exc.reason})") from exc

    def rpc(self, method: str, params: dict | None = None,
            notification: bool = False, retries: int = 2) -> dict | None:
        """One JSON-RPC round trip. Returns the result object (or None)."""
        self._next_id += 1
        message_id = None if notification else self._next_id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if message_id is not None:
            payload["id"] = message_id

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                messages, headers = self._post_once(payload)
                new_session = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
                if new_session and not self.session_id:
                    self.session_id = new_session
                for msg in messages:
                    if msg.get("id") == message_id:
                        if "error" in msg:
                            err = msg["error"]
                            raise SuperDocsError(
                                f"MCP error {err.get('code')}: {err.get('message')}")
                        return msg.get("result")
                if notification:
                    return None
                last_error = SuperDocsError(f"No response for '{method}'")
            except SuperDocsError as exc:
                if "HTTP 4" in str(exc) and attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise
            time.sleep(1.5 * (attempt + 1))
        raise last_error or SuperDocsError(f"'{method}' failed")

    # ----------------------------------------------------------- lifecycle

    def connect(self) -> None:
        result = self.rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "strpack", "version": "1.0"},
        })
        self.rpc("notifications/initialized", {}, notification=True)
        server = ((result or {}).get("serverInfo") or {})
        if not self.quiet:
            pass  # caller decides what to print

    # ------------------------------------------------------------- tooling

    def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool; unwrap content[].text and parse JSON when possible.

        Accepts both ``superdocs_health`` and ``health`` style names.
        """
        if self.session_id is None:
            self.connect()
        server_name = tool_name.removeprefix("superdocs_")
        result = self.rpc("tools/call", {"name": server_name, "arguments": arguments})
        if result is None:
            raise SuperDocsError(f"Tool '{tool_name}' returned nothing")
        if result.get("isError"):
            texts = "".join(c.get("text", "") for c in result.get("content", []))
            raise SuperDocsError(f"Tool '{tool_name}' failed: {texts[:300]}")
        contents = result.get("content", [])
        if not contents:
            return None
        text = contents[0].get("text", "")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text

    # ------------------------------------------------------ high level API

    def ping(self) -> tuple[bool, str]:
        try:
            self.connect()
            status = self.call("superdocs_health", {}) or {}
            return True, str(status.get("status", "ok"))
        except SuperDocsError as exc:
            return False, str(exc)

    def upload_image_file(self, path: str | Path) -> dict:
        path = Path(path)
        ctype = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
        }.get(path.suffix.lower(), "application/octet-stream")
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        result = self.call("superdocs_upload_image_base64", {
            "image_base64": data, "filename": path.name, "content_type": ctype})
        if not isinstance(result, dict) or not result.get("url"):
            raise SuperDocsError(f"Image upload failed for {path.name}: {str(result)[:200]}")
        return result

    @staticmethod
    def _b64(html: str) -> str:
        return base64.b64encode(html.encode("utf-8")).decode("ascii")

    def init_session(self) -> str:
        result = self.call("superdocs_init_session", {}) or {}
        sid = result.get("session_id") or result.get("id")
        if not sid:
            raise SuperDocsError(f"Could not create session: {str(result)[:200]}")
        return sid

    def upload_document(self, session_id: str, html: str, filename: str) -> dict:
        return self.call("superdocs_upload_document_base64", {
            "session_id": session_id, "filename": filename,
            "file_base64": self._b64(html), "return_html": False}) or {}

    def session_documents(self, session_id: str) -> list[dict]:
        result = self.call("superdocs_list_session_documents", {
            "session_id": session_id}) or {}
        docs = result.get("documents") or result.get("docs") or []
        return docs if isinstance(docs, list) else []

    def add_running_furniture(self, session_id: str,
                              header_text: str, footer_text: str,
                              rounds: int = 5) -> tuple[bool, str]:
        """Create/replace running page header+footer via surgical chat edits.

        Big documents make the editor pause mid-task ("continue?"), so we
        keep nudging until structure.parts reports both running parts.
        """
        base_message = (
            "Document housekeeping - touch ONLY the running page furniture.\n"
            f"1) Set the running page HEADER text to exactly: {header_text}\n"
            f"2) Set the running page FOOTER text to exactly: {footer_text}\n"
            "Style both: small (8.5pt), gray (#68717A), uppercase, letter-spaced. "
            "Do NOT modify, reword, move or restyle ANY body content. "
            "Complete ALL steps autonomously - do not pause to ask.")
        note = ""
        for attempt in range(rounds):
            message = base_message if attempt == 0 else (
                "Continue. Finish every remaining step now without asking "
                "anything; confirm when both running parts are set.")
            result = self.call("chat", {"session_id": session_id,
                                        "message": message,
                                        "response_mode": "compact"})
            note = (result.get("response", "") if isinstance(result, dict)
                    else str(result))
            if self._has_furniture(session_id):
                return True, note
            time.sleep(2.0)
        return False, note

    def _has_furniture(self, session_id: str) -> bool:
        """Out-of-flow parts never appear in body HTML - check structure.parts."""
        try:
            docs = self.session_documents(session_id)
            for d in docs:
                durable = d.get("durable_document_id") or d.get("document_id")
                if not durable:
                    continue
                detail = self.call("get_document_detail", {"document_id": durable})
                parts = ((detail.get("structure") or {}).get("parts")) or []
                kinds = {p.get("part_type") for p in parts if isinstance(p, dict)}
                if {"header", "footer"} <= kinds:
                    return True
        except SuperDocsError:
            return False
        return False

    def request_download(self, session_id: str, fmt: str,
                         filename: str, paper_size: str = "A4",
                         orientation: str = "portrait") -> str:
        result = self.call("superdocs_request_download_url", {
            "session_id": session_id, "format": fmt, "filename": filename,
            "options": {"paper_size": paper_size, "orientation": orientation,
                        "margins": "normal"}}) or {}
        url = result.get("download_url")
        if not url:
            raise SuperDocsError(f"Export did not return a URL: {str(result)[:200]}")
        return url

    def export_adhoc(self, html: str, fmt: str, filename: str,
                     paper_size: str = "A4", orientation: str = "portrait",
                     margins: str = "normal") -> str:
        """Export inline HTML without creating a session. Returns download URL."""
        result = self.call("superdocs_export_document", {
            "html": html, "format": fmt, "filename": filename,
            "options": {"paper_size": paper_size, "orientation": orientation,
                        "margins": margins}}) or {}
        url = result.get("download_url")
        if not url:
            raise SuperDocsError(f"Ad-hoc export failed: {str(result)[:200]}")
        return url

    def download(self, url: str, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp, \
                open(dest, "wb") as fh:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
        return dest
