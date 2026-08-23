"""Gate ⑤ — Argument policy: force, deny, and max controls."""

from __future__ import annotations

import json

import httpx

from tests.conftest import LEGAL_TOKEN, FakeUpstream

CT = "application/json"
OK_RESULT = b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}'


def _call(tool: str, arguments: dict | None = None) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": tool, "arguments": arguments or {}},
        }
    ).encode()


def _headers(token: str = LEGAL_TOKEN) -> dict[str, str]:
    return {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {token}"}


# ──── force ──────────────────────────────────────────────────────────────


async def test_force_global_arg(gw_args: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("chat_async", {"cross_session_memory": True, "message": "hi"})
    await gw_args.post("/mcp", content=body, headers=_headers())
    req = upstream.requests[0]
    forwarded = json.loads(req.content)
    assert forwarded["params"]["arguments"]["cross_session_memory"] is False


async def test_force_tool_specific_arg(gw_args: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("chat_async", {"message": "hi"})
    await gw_args.post("/mcp", content=body, headers=_headers())
    req = upstream.requests[0]
    forwarded = json.loads(req.content)
    assert forwarded["params"]["arguments"]["approval_mode"] == "ask_every_time"


async def test_force_does_not_apply_to_other_tools(
    gw_args: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("health", {"message": "hi"})
    await gw_args.post("/mcp", content=body, headers=_headers())
    req = upstream.requests[0]
    forwarded = json.loads(req.content)
    assert "approval_mode" not in forwarded["params"]["arguments"]


# ──── deny ───────────────────────────────────────────────────────────────


async def test_deny_matching_value_rejects(gw_args: httpx.AsyncClient) -> None:
    body = _call("archive_document", {"force": True})
    resp = await gw_args.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 403
    assert "denied" in resp.json()["error"]["message"]


async def test_deny_non_matching_value_passes(
    gw_args: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("archive_document", {"force": False})
    resp = await gw_args.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 200


async def test_deny_absent_arg_passes(gw_args: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("archive_document", {})
    resp = await gw_args.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 200


# ──── max ────────────────────────────────────────────────────────────────


async def test_max_within_limit_passes(gw_args: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("chat_async", {"model_tier": "pro"})
    await gw_args.post("/mcp", content=body, headers=_headers())
    assert upstream.requests


async def test_max_exceeds_limit_rejects(gw_args: httpx.AsyncClient) -> None:
    body = _call("chat_async", {"model_tier": "max"})
    resp = await gw_args.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 403
    assert "exceeds max" in resp.json()["error"]["message"]


async def test_max_unknown_tier_rejects(gw_args: httpx.AsyncClient) -> None:
    body = _call("chat_async", {"model_tier": "ultra"})
    resp = await gw_args.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 403
