"""Auth is real: no key / bad key -> 401; admin endpoints need the admin key."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_missing_key_is_unauthorized(client):
    resp = await client.get("/v1/documents")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_bad_key_is_unauthorized(client):
    resp = await client.get("/v1/documents", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_key_can_list(client, make_tenant):
    _, headers = await make_tenant()
    resp = await client.get("/v1/documents", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"documents": []}


@pytest.mark.asyncio
async def test_tenant_creation_requires_admin(client):
    resp = await client.post("/v1/admin/tenants", json={"name": "x"})
    assert resp.status_code == 401

    resp = await client.post(
        "/v1/admin/tenants",
        json={"name": "x"},
        headers={"Authorization": "Bearer wrong-admin"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health_is_public(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
