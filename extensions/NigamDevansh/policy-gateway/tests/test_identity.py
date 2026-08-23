"""Gate ① — Identity: token exchange and team resolution."""

from __future__ import annotations

import json

import httpx

from tests.conftest import LEGAL_TOKEN, MKTG_TOKEN, UPSTREAM_KEY, FakeUpstream

CT = "application/json"


def _rpc(method: str = "tools/list") -> bytes:
    return json.dumps({"jsonrpc": "2.0", "method": method, "id": 1}).encode()


def _headers(token: str) -> dict[str, str]:
    return {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {token}"}


async def test_valid_legal_token(gw_policy: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')
    resp = await gw_policy.post("/mcp", content=_rpc(), headers=_headers(LEGAL_TOKEN))
    assert resp.status_code == 200


async def test_valid_mktg_token(gw_policy: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')
    resp = await gw_policy.post("/mcp", content=_rpc(), headers=_headers(MKTG_TOKEN))
    assert resp.status_code == 200


async def test_unknown_token_returns_401(gw_policy: httpx.AsyncClient) -> None:
    resp = await gw_policy.post("/mcp", content=_rpc(), headers=_headers("gw_unknown_token"))
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == -32000
    assert "unauthorized" in body["error"]["message"]


async def test_missing_auth_header_returns_401(gw_policy: httpx.AsyncClient) -> None:
    headers = {"Content-Type": CT, "Accept": CT}
    resp = await gw_policy.post("/mcp", content=_rpc(), headers=headers)
    assert resp.status_code == 401


async def test_empty_bearer_returns_401(gw_policy: httpx.AsyncClient) -> None:
    resp = await gw_policy.post("/mcp", content=_rpc(), headers=_headers(""))
    assert resp.status_code == 401


async def test_non_bearer_scheme_returns_401(gw_policy: httpx.AsyncClient) -> None:
    headers = {"Content-Type": CT, "Accept": CT, "Authorization": "Basic dXNlcjpwYXNz"}
    resp = await gw_policy.post("/mcp", content=_rpc(), headers=headers)
    assert resp.status_code == 401


async def test_upstream_receives_swapped_key(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')
    await gw_policy.post("/mcp", content=_rpc(), headers=_headers(LEGAL_TOKEN))
    req = upstream.requests[0]
    assert req.headers["authorization"] == f"Bearer {UPSTREAM_KEY}"


async def test_upstream_never_sees_gateway_token(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')
    await gw_policy.post("/mcp", content=_rpc(), headers=_headers(LEGAL_TOKEN))
    req = upstream.requests[0]
    assert LEGAL_TOKEN not in req.headers["authorization"]


async def test_401_does_not_reach_upstream(
    gw_policy: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    await gw_policy.post("/mcp", content=_rpc(), headers=_headers("bad_token"))
    assert len(upstream.requests) == 0
