"""Gate ④ — Tool allowlist + tools/list response filtering."""

from __future__ import annotations

import json

import httpx

from tests.conftest import LEGAL_TOKEN, MKTG_TOKEN, FakeUpstream

CT = "application/json"


def _rpc_call(tool: str, arguments: dict | None = None) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": tool, "arguments": arguments or {}},
        }
    ).encode()


def _rpc(method: str = "tools/list") -> bytes:
    return json.dumps({"jsonrpc": "2.0", "method": method, "id": 1, "params": {}}).encode()


def _headers(token: str = LEGAL_TOKEN) -> dict[str, str]:
    return {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {token}"}


# ──── tools/call allowlist ───────────────────────────────────────────────────


async def test_allowed_tool_passes(gw_policy: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}')
    resp = await gw_policy.post("/mcp", content=_rpc_call("health"), headers=_headers())
    assert resp.status_code == 200
    assert len(upstream.requests) == 1


async def test_denied_tool_returns_error(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    resp = await gw_policy.post("/mcp", content=_rpc_call("archive_document"), headers=_headers())
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == -32602
    assert "archive_document" in body["error"]["message"]
    assert "team=legal" in body["error"]["message"]
    assert len(upstream.requests) == 0


async def test_denied_tool_includes_alternatives(
    gw_policy: httpx.AsyncClient,
) -> None:
    resp = await gw_policy.post("/mcp", content=_rpc_call("archive_document"), headers=_headers())
    body = resp.json()
    assert "permitted alternatives:" in body["error"]["message"]
    assert "health" in body["error"]["message"]


async def test_default_deny_applied(gw_policy: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    resp = await gw_policy.post("/mcp", content=_rpc_call("request_upload_url"), headers=_headers())
    assert resp.status_code == 403
    assert len(upstream.requests) == 0


async def test_wildcard_allows_all(gw_policy: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}')
    resp = await gw_policy.post(
        "/mcp", content=_rpc_call("some_random_tool"), headers=_headers(MKTG_TOKEN)
    )
    assert resp.status_code == 200
    assert len(upstream.requests) == 1


async def test_deny_wins_over_wildcard(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    resp = await gw_policy.post(
        "/mcp", content=_rpc_call("archive_document"), headers=_headers(MKTG_TOKEN)
    )
    assert resp.status_code == 403
    assert len(upstream.requests) == 0


async def test_default_deny_wins_over_wildcard(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    resp = await gw_policy.post(
        "/mcp", content=_rpc_call("request_download_url"), headers=_headers(MKTG_TOKEN)
    )
    assert resp.status_code == 403
    assert len(upstream.requests) == 0


# ──── tools/list response filtering ─────────────────────────────────────────

_FULL_TOOLS = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {"name": "health", "description": "Check health"},
                {"name": "chat_async", "description": "AI chat"},
                {"name": "archive_document", "description": "Archive doc"},
                {"name": "request_upload_url", "description": "Pre-signed upload"},
                {"name": "export_document", "description": "Export"},
            ]
        },
    }
).encode()


async def test_tools_list_filtered_for_legal(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, _FULL_TOOLS)
    resp = await gw_policy.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    tools = resp.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {"health", "chat_async", "export_document"}
    assert "archive_document" not in names
    assert "request_upload_url" not in names


async def test_tools_list_filtered_for_marketing(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, _FULL_TOOLS)
    resp = await gw_policy.post("/mcp", content=_rpc("tools/list"), headers=_headers(MKTG_TOKEN))
    tools = resp.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "health" in names
    assert "chat_async" in names
    assert "export_document" in names
    assert "archive_document" not in names
    assert "request_upload_url" not in names


async def test_tools_list_upstream_error_passed_through(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(500, b'{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"fail"}}')
    resp = await gw_policy.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    assert resp.status_code == 500
