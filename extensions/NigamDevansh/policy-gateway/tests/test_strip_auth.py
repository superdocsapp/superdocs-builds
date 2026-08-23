"""Gate ③ — Strip arguments.authorization (the bypass vector)."""

from __future__ import annotations

import json

import httpx

from tests.conftest import LEGAL_TOKEN, FakeUpstream

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


def _headers(token: str = LEGAL_TOKEN) -> dict[str, str]:
    return {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {token}"}


async def test_authorization_arg_stripped(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}')
    body = _rpc_call("health", {"authorization": "Bearer sk_stolen_key"})
    await gw_policy.post("/mcp", content=body, headers=_headers())
    req = upstream.requests[0]
    forwarded = json.loads(req.content)
    assert "authorization" not in forwarded["params"]["arguments"]


async def test_other_arguments_preserved(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}')
    body = _rpc_call(
        "health",
        {"authorization": "Bearer sk_stolen", "keep_this": "value"},
    )
    await gw_policy.post("/mcp", content=body, headers=_headers())
    req = upstream.requests[0]
    forwarded = json.loads(req.content)
    args = forwarded["params"]["arguments"]
    assert "authorization" not in args
    assert args["keep_this"] == "value"


async def test_no_authorization_arg_unchanged(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}')
    body = _rpc_call("health", {"key": "value"})
    await gw_policy.post("/mcp", content=body, headers=_headers())
    req = upstream.requests[0]
    forwarded = json.loads(req.content)
    assert forwarded["params"]["arguments"] == {"key": "value"}


async def test_non_tools_call_not_affected(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')
    rpc = {"jsonrpc": "2.0", "method": "tools/list", "id": 1, "params": {}}
    await gw_policy.post("/mcp", content=json.dumps(rpc).encode(), headers=_headers())
    req = upstream.requests[0]
    forwarded = json.loads(req.content)
    assert forwarded["method"] == "tools/list"
