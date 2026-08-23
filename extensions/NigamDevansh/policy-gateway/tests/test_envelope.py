"""Gate ② — JSON-RPC envelope validation (policy mode only)."""

from __future__ import annotations

import httpx

from tests.conftest import LEGAL_TOKEN, FakeUpstream

CT = "application/json"


def _headers() -> dict[str, str]:
    return {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {LEGAL_TOKEN}"}


async def test_invalid_json(gw_policy: httpx.AsyncClient) -> None:
    resp = await gw_policy.post("/mcp", content=b"not json{{{", headers=_headers())
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32700


async def test_body_is_array(gw_policy: httpx.AsyncClient) -> None:
    resp = await gw_policy.post("/mcp", content=b"[1,2,3]", headers=_headers())
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32600


async def test_missing_jsonrpc_field(gw_policy: httpx.AsyncClient) -> None:
    resp = await gw_policy.post(
        "/mcp", content=b'{"method":"tools/list","id":1}', headers=_headers()
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32600


async def test_wrong_jsonrpc_version(gw_policy: httpx.AsyncClient) -> None:
    resp = await gw_policy.post(
        "/mcp",
        content=b'{"jsonrpc":"1.0","method":"tools/list","id":1}',
        headers=_headers(),
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32600


async def test_missing_method(gw_policy: httpx.AsyncClient) -> None:
    resp = await gw_policy.post("/mcp", content=b'{"jsonrpc":"2.0","id":1}', headers=_headers())
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32600


async def test_method_not_string(gw_policy: httpx.AsyncClient) -> None:
    resp = await gw_policy.post(
        "/mcp", content=b'{"jsonrpc":"2.0","method":42,"id":1}', headers=_headers()
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == -32600


async def test_passthrough_does_not_validate_envelope(
    gw: httpx.AsyncClient, upstream: FakeUpstream
) -> None:
    """Without policy, even garbage JSON is forwarded transparently."""
    upstream.respond(200, b'{"ok":true}')
    resp = await gw.post(
        "/mcp",
        content=b"not json",
        headers={"Content-Type": CT, "Accept": CT, "Authorization": "Bearer sk_test"},
    )
    assert resp.status_code == 200
