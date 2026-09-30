"""Conformance suite: proxied responses are byte-identical to upstream."""

from __future__ import annotations

import json

import httpx
import pytest

from tests.conftest import FakeUpstream

ACCEPT = "application/json"
CT = "application/json"


def _rpc(method: str, params: dict | None = None) -> bytes:
    obj: dict = {"jsonrpc": "2.0", "method": method, "id": 1}
    if params is not None:
        obj["params"] = params
    return json.dumps(obj, separators=(",", ":")).encode()


def _headers(auth: str = "Bearer sk_test") -> dict[str, str]:
    return {"Content-Type": CT, "Accept": ACCEPT, "Authorization": auth}


# ──── Body identity ──────────────────────────────────────────────────────────

_INIT_PARAMS = {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "test", "version": "1"},
}

_BODY_CASES: list[tuple[str, str, dict | None, bytes]] = [
    (
        "initialize",
        "initialize",
        _INIT_PARAMS,
        b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05",'
        b'"capabilities":{"tools":{}},"serverInfo":{"name":"superdocs","version":"1.0"}}}',
    ),
    (
        "tools_list",
        "tools/list",
        {},
        b'{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"health"}]}}',
    ),
    (
        "tools_call",
        "tools/call",
        {"name": "health", "arguments": {}},
        b'{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}',
    ),
    (
        "prompts_list",
        "prompts/list",
        {},
        b'{"jsonrpc":"2.0","id":1,"result":{"prompts":[]}}',
    ),
    (
        "resources_list",
        "resources/list",
        {},
        b'{"jsonrpc":"2.0","id":1,"result":{"resources":[]}}',
    ),
]


@pytest.mark.parametrize(
    "method,params,upstream_body",
    [(m, p, b) for _, m, p, b in _BODY_CASES],
    ids=[name for name, *_ in _BODY_CASES],
)
async def test_body_identical(
    gw: httpx.AsyncClient,
    upstream: FakeUpstream,
    method: str,
    params: dict | None,
    upstream_body: bytes,
) -> None:
    upstream.respond(200, upstream_body)
    resp = await gw.post("/mcp", content=_rpc(method, params), headers=_headers())
    assert resp.content == upstream_body
    assert resp.status_code == 200


# ──── Status codes ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", [401, 403, 406, 429, 500, 502])
async def test_upstream_status_passed_through(
    gw: httpx.AsyncClient,
    upstream: FakeUpstream,
    status: int,
) -> None:
    body = b'{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"fail"}}'
    upstream.respond(status, body)
    resp = await gw.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    assert resp.status_code == status
    assert resp.content == body


# ──── Request headers forwarded ──────────────────────────────────────────────


async def test_accept_forwarded(gw: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b"{}")
    await gw.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    req = upstream.requests[0]
    assert req.headers["accept"] == ACCEPT


async def test_authorization_forwarded(gw: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b"{}")
    await gw.post("/mcp", content=_rpc("tools/list"), headers=_headers("Bearer sk_secret"))
    req = upstream.requests[0]
    assert req.headers["authorization"] == "Bearer sk_secret"


async def test_content_type_forwarded(gw: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b"{}")
    await gw.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    req = upstream.requests[0]
    assert req.headers["content-type"] == CT


# ──── Request body forwarded ─────────────────────────────────────────────────


async def test_request_body_forwarded_verbatim(
    gw: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b"{}")
    body = _rpc("tools/call", {"name": "health", "arguments": {"key": "value"}})
    await gw.post("/mcp", content=body, headers=_headers())
    req = upstream.requests[0]
    assert req.content == body


# ──── Response headers ───────────────────────────────────────────────────────


async def test_response_content_type_preserved(
    gw: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b"{}", headers={"content-type": "application/json; charset=utf-8"})
    resp = await gw.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    assert resp.headers["content-type"] == "application/json; charset=utf-8"


# ──── Both /mcp paths ────────────────────────────────────────────────────────


async def test_mcp_path(gw: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b'{"ok":true}')
    resp = await gw.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    assert resp.status_code == 200
    assert resp.content == b'{"ok":true}'


async def test_mcp_slash_path(gw: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.respond(200, b'{"ok":true}')
    resp = await gw.post("/mcp/", content=_rpc("tools/list"), headers=_headers())
    assert resp.status_code == 200
    assert resp.content == b'{"ok":true}'


# ──── Upstream URL ───────────────────────────────────────────────────────────


async def test_request_forwarded_to_upstream_url(
    gw: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    upstream.respond(200, b"{}")
    await gw.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    req = upstream.requests[0]
    assert str(req.url) == "https://upstream.test/mcp"


# ──── Connection error ───────────────────────────────────────────────────────


async def test_upstream_unreachable(gw: httpx.AsyncClient, upstream: FakeUpstream) -> None:
    upstream.error(httpx.ConnectError("connection refused"))
    resp = await gw.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == -32000
    assert "upstream" in body["error"]["message"]


# ──── Health endpoint ────────────────────────────────────────────────────────


async def test_health(gw: httpx.AsyncClient) -> None:
    resp = await gw.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
