"""Plumbline as an MCP server, so a coding agent can drive it.

This is the point of the tool. A developer working in Cursor or Claude Code
changes a default, and the agent that made the change can ask, in the same
breath, which documentation just became false -- and correct it, through a gate,
without leaving the editor.

    claude mcp add plumbline -- python /abs/path/plumbline.py serve

Deliberately no dependency on the `mcp` package: this speaks the JSON-RPC
protocol over stdio directly, using nothing but the standard library, so it
installs nowhere and runs anywhere Python does.

The gate is a tool, not a flag. `plumbline_apply` refuses to write anything that
has not been through `plumbline_decide`, so an agent cannot quietly edit a
repository's documentation on its own.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import plumbline as pl

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "plumbline_scan",
        "description": (
            "Read what the code actually says -- every function signature, "
            "default, raised exception and module constant -- straight from the "
            "Python AST. No model is involved, so this is authoritative. Costs "
            "nothing and touches no network."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string",
                                    "description": "Path to the package directory"}},
        },
    },
    {
        "name": "plumbline_check",
        "description": (
            "Check whether a document is still true to the code. Extracts the "
            "checkable claims the document makes, verifies each against the AST, "
            "and returns the drift: what the document says, what the code says, "
            "and the file and line that settles it. Run this after changing a "
            "public default, signature or constant."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "doc": {"type": "string", "description": "Path to the .html document"},
            },
        },
    },
    {
        "name": "plumbline_fix",
        "description": (
            "Draft corrections for the drift found by plumbline_check. The draft "
            "is held for review and NOTHING is written to the repository. Returns "
            "the proposed before/after for each correction."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "plumbline_decide",
        "description": (
            "Approve or reject the drafted corrections. This is the human gate. "
            "An approval is verified before it is staged: if the edit does not "
            "actually carry the code's values, it is refused."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["approve", "reject"]},
                "reason": {"type": "string"},
                "by": {"type": "string", "description": "Who is deciding"},
            },
            "required": ["verdict"],
        },
    },
    {
        "name": "plumbline_apply",
        "description": (
            "Write the approved document back into the repository, keeping a copy "
            "of the previous version so `git diff` shows exactly what changed. "
            "Refuses unless a decision has been recorded."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "plumbline_status",
        "description": "Where the current document stands: drift found, awaiting review, approved, or applied.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _capture(fn, *a, **kw) -> str:
    """Run a CLI command and return what it printed."""
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **kw)
    return buf.getvalue().strip() or "(no output)"


def _args(**kw):
    return type("A", (), kw)()


def call_tool(name: str, arguments: dict) -> str:
    if name == "plumbline_scan":
        return _capture(pl.cmd_scan, _args(
            code=arguments.get("code", "sample-repo/meridian_sdk")))

    if name == "plumbline_check":
        out = _capture(pl.cmd_check, _args(
            code=arguments.get("code", "sample-repo/meridian_sdk"),
            doc=arguments.get("doc", "sample-repo/docs/api-reference.html")))
        st = pl.load_state()
        return out + "\n\nstructured:\n" + json.dumps(
            {"status": st.get("status"), "drifts": st.get("drifts", [])}, indent=2)

    if name == "plumbline_fix":
        return _capture(pl.cmd_fix, _args())

    if name == "plumbline_decide":
        return _capture(pl.cmd_decide, _args(
            verdict=arguments["verdict"],
            reason=arguments.get("reason", ""),
            by=arguments.get("by", "mcp-client")))

    if name == "plumbline_apply":
        return _capture(pl.cmd_apply, _args())

    if name == "plumbline_status":
        st = pl.load_state()
        return json.dumps({
            "status": st.get("status", "nothing checked yet"),
            "doc": st.get("doc"),
            "claims": st.get("claims"),
            "verified": st.get("verified"),
            "drifts": len(st.get("drifts", [])),
            "checked_at": st.get("checked_at"),
            "decision": st.get("decision"),
        }, indent=2)

    raise KeyError(f"no such tool: {name}")


def _send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _result(req_id, text: str, is_error: bool = False) -> None:
    _send({"jsonrpc": "2.0", "id": req_id,
           "result": {"content": [{"type": "text", "text": text}],
                      "isError": is_error}})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method, req_id = req.get("method"), req.get("id")

        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "plumbline", "version": "1.0.0"},
            }})
        elif method == "notifications/initialized":
            pass  # a notification; no reply
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            params = req.get("params") or {}
            try:
                text = call_tool(params.get("name", ""), params.get("arguments") or {})
                _result(req_id, text)
            except Exception as exc:  # noqa: BLE001
                # An error the agent can act on, never a silent failure.
                print(traceback.format_exc(), file=sys.stderr)
                _result(req_id, f"{type(exc).__name__}: {exc}", is_error=True)
        elif req_id is not None:
            _send({"jsonrpc": "2.0", "id": req_id,
                   "error": {"code": -32601, "message": f"method not found: {method}"}})


if __name__ == "__main__":
    main()
