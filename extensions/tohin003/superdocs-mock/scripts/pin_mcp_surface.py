#!/usr/bin/env python3
"""Capture the live SuperDocs MCP surface and pin it to spec/mcp-tools.json.

The MCP tool surface is served live from the SuperDocs backend -- the Claude Code plugin
carries only a manifest -- so tools and prompts can change with no release anywhere. That
makes this the most drift-prone artifact in the project, and the reason it gets its own
pin rather than riding along with openapi.json.

This script is also the drift watcher's engine (Phase 6): re-run it and diff the result
against the committed pin.

Reads the key from ~/.config/superdocs/api-key or $SUPERDOCS_API_KEY. Never prints it.
Non-billable: a handshake and two list calls spend no operations.

    python scripts/pin_mcp_surface.py            # write spec/mcp-tools.json
    python scripts/pin_mcp_surface.py --check    # compare against the pin, don't write
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

ENDPOINT = "https://api.superdocs.app/mcp/"
PIN = Path(__file__).resolve().parent.parent / "spec" / "mcp-tools.json"
KEY_FILE = Path.home() / ".config" / "superdocs" / "api-key"

# Newest first: the server replies with the version it actually speaks, so we start
# modern and accept whatever comes back rather than hard-coding one revision.
PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]

CLIENT_INFO = {"name": "sdmock-surface-pin", "version": "0.1.0"}


def load_key() -> str:
    key = os.environ.get("SUPERDOCS_API_KEY")
    if not key and KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit(
            f"No API key. Put one in {KEY_FILE} (chmod 600) or set SUPERDOCS_API_KEY."
        )
    return key


def parse_body(response: httpx.Response) -> dict[str, Any]:
    """Streamable HTTP may answer with JSON or with a one-shot SSE frame."""
    ctype = response.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in response.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        raise ValueError(f"SSE response carried no data frame: {response.text[:200]!r}")
    return response.json()


class Session:
    def __init__(self, client: httpx.Client, key: str) -> None:
        self.client = client
        self.key = key
        self.session_id: str | None = None
        self.protocol: str | None = None
        self.next_id = 0

    def headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        payload = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            payload["params"] = params
        r = self.client.post(ENDPOINT, headers=self.headers(), json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} -> HTTP {r.status_code}: {r.text[:300]}")
        body = parse_body(r)
        if "error" in body:
            raise RuntimeError(f"{method} -> JSON-RPC error: {body['error']}")
        return body.get("result", {})

    def notify(self, method: str) -> None:
        r = self.client.post(
            ENDPOINT,
            headers=self.headers(),
            json={"jsonrpc": "2.0", "method": method},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"{method} -> HTTP {r.status_code}: {r.text[:300]}")

    def initialize(self) -> dict[str, Any]:
        last: Exception | None = None
        for version in PROTOCOL_VERSIONS:
            self.next_id += 1
            payload = {
                "jsonrpc": "2.0",
                "id": self.next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            }
            r = self.client.post(ENDPOINT, headers=self.headers(), json=payload)
            if r.status_code >= 400:
                last = RuntimeError(f"initialize -> HTTP {r.status_code}: {r.text[:300]}")
                continue
            body = parse_body(r)
            if "error" in body:
                last = RuntimeError(f"initialize -> {body['error']}")
                continue
            self.session_id = r.headers.get("mcp-session-id")
            result = body.get("result", {})
            # Trust the server's answer over our request.
            self.protocol = result.get("protocolVersion", version)
            return result
        raise last or RuntimeError("initialize failed for every protocol version tried")


def capture() -> dict[str, Any]:
    key = load_key()
    with httpx.Client(timeout=60.0) as client:
        s = Session(client, key)
        init = s.initialize()
        try:
            s.notify("notifications/initialized")
        except RuntimeError as exc:  # not fatal for a read-only capture
            print(f"  note: initialized notification rejected ({exc})", file=sys.stderr)

        tools = s.call("tools/list").get("tools", [])
        try:
            prompts = s.call("prompts/list").get("prompts", [])
        except RuntimeError as exc:
            print(f"  note: prompts/list failed ({exc})", file=sys.stderr)
            prompts = []

        return {
            "_pin": {
                "endpoint": ENDPOINT,
                "transport": "streamable-http",
                "protocol_version": s.protocol,
                "tool_count": len(tools),
                "prompt_count": len(prompts),
            },
            "initialize": init,
            "tools": sorted(tools, key=lambda t: t.get("name", "")),
            "prompts": sorted(prompts, key=lambda p: p.get("name", "")),
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare against the pin only")
    args = ap.parse_args()

    surface = capture()
    meta = surface["_pin"]
    server = surface["initialize"].get("serverInfo", {})

    print(f"endpoint         : {meta['endpoint']}")
    print(f"protocol version : {meta['protocol_version']}")
    print(f"server           : {server.get('name')} {server.get('version')}")
    print(f"tools            : {meta['tool_count']}")
    print(f"prompts          : {meta['prompt_count']}")
    has_instructions = bool(surface["initialize"].get("instructions"))
    print(f"instructions     : {'present' if has_instructions else 'ABSENT'}  (B-096)")

    rendered = json.dumps(surface, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if args.check:
        if not PIN.exists():
            print("\nno pin on disk to compare against", file=sys.stderr)
            return 1
        if PIN.read_text(encoding="utf-8") == rendered:
            print("\nsurface matches the pin")
            return 0
        print("\nDRIFT: live surface differs from spec/mcp-tools.json", file=sys.stderr)
        return 2

    PIN.write_text(rendered, encoding="utf-8")
    print(f"\nwrote {PIN.relative_to(Path.cwd())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
