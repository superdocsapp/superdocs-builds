"""Gate ⑦ — Quota: billable-tool limits, reserve/settle/release lifecycle."""

from __future__ import annotations

import json

import httpx

from tests.conftest import LEGAL_TOKEN, MKTG_TOKEN, FakeUpstream

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


# ──── Billable tool reserves quota ─────────────────────────────────────


async def test_billable_tool_reserves_and_settles(
    gw_quota: httpx.AsyncClient,
    upstream: FakeUpstream,
    quota_store,
) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("chat_async", {"message": "hi"})
    resp = await gw_quota.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 200
    tq = quota_store.get("legal")
    assert tq is not None
    assert tq.used == 1
    assert tq.reserved == 0


# ──── Non-billable tool skips quota entirely ───────────────────────────


async def test_non_billable_tool_skips_quota(
    gw_quota: httpx.AsyncClient,
    upstream: FakeUpstream,
    quota_store,
) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("health", {"message": "hi"})
    resp = await gw_quota.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 200
    tq = quota_store.get("legal")
    assert tq is not None
    assert tq.used == 0
    assert tq.reserved == 0


# ──── Exhausted quota returns 429 ──────────────────────────────────────


async def test_quota_exhausted_returns_429(
    gw_quota: httpx.AsyncClient,
    upstream: FakeUpstream,
    quota_store,
) -> None:
    tq = quota_store.get("legal")
    assert tq is not None
    tq.used = tq.monthly_limit

    body = _call("chat_async", {"message": "hi"})
    resp = await gw_quota.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 429
    assert "quota exhausted" in resp.json()["error"]["message"]
    assert len(upstream.requests) == 0


# ──── Failed upstream releases reservation ─────────────────────────────


async def test_upstream_error_releases_reservation(
    gw_quota: httpx.AsyncClient,
    upstream: FakeUpstream,
    quota_store,
) -> None:
    upstream.respond(500, b'{"error":"internal"}')
    body = _call("chat_async", {"message": "hi"})
    resp = await gw_quota.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 500
    tq = quota_store.get("legal")
    assert tq is not None
    assert tq.used == 0
    assert tq.reserved == 0


async def test_connection_error_releases_reservation(
    gw_quota: httpx.AsyncClient,
    upstream: FakeUpstream,
    quota_store,
) -> None:
    upstream.error(httpx.ConnectError("connection refused"))
    body = _call("chat_async", {"message": "hi"})
    resp = await gw_quota.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 502
    tq = quota_store.get("legal")
    assert tq is not None
    assert tq.used == 0
    assert tq.reserved == 0


# ──── Team without quota is unlimited ──────────────────────────────────


async def test_team_without_quota_unlimited(
    gw_quota: httpx.AsyncClient,
    upstream: FakeUpstream,
    quota_store,
) -> None:
    upstream.respond(200, OK_RESULT)
    body = _call("chat_async", {"message": "hi"})
    resp = await gw_quota.post("/mcp", content=body, headers=_headers(MKTG_TOKEN))
    assert resp.status_code == 200
    assert quota_store.get("marketing") is None


# ──── Quota drains correctly across multiple calls ─────────────────────


async def test_quota_drains_over_multiple_calls(
    gw_quota: httpx.AsyncClient,
    upstream: FakeUpstream,
    quota_store,
) -> None:
    tq = quota_store.get("legal")
    assert tq is not None
    limit = tq.monthly_limit

    for i in range(limit):
        upstream.respond(200, OK_RESULT)
        body = _call("chat_async", {"message": f"call {i}"})
        resp = await gw_quota.post("/mcp", content=body, headers=_headers())
        assert resp.status_code == 200

    assert tq.used == limit
    body = _call("chat_async", {"message": "one too many"})
    resp = await gw_quota.post("/mcp", content=body, headers=_headers())
    assert resp.status_code == 429
