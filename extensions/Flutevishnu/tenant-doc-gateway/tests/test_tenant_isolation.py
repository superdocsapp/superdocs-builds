"""Tenant Isolation Verification Suite.

These tests actively attempt to cross the tenant boundary to assert failure.
Isolation is demonstrated by simulated attacks that verify the boundaries.

Contract under test — the service must NEVER:
- return, edit, export, or reveal the existence of another tenant's document/job.
Cross-tenant access returns 404 (not 403) to prevent existence oracles.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenants_document(ready_document, client, make_tenant):
    _, _, doc_id = ready_document  # owned by tenant A
    _, attacker_headers = await make_tenant()  # tenant B

    # Control: an attacker asking for the real id gets 404, same as a random id.
    resp = await client.get(f"/v1/documents/{doc_id}", headers=attacker_headers)
    assert resp.status_code == 404

    random_id = uuid.uuid4()
    resp_random = await client.get(f"/v1/documents/{random_id}", headers=attacker_headers)
    assert resp_random.status_code == 404
    # Identical responses => no way to tell a real foreign id from a fake one.
    assert resp.json() == resp_random.json()


@pytest.mark.asyncio
async def test_owner_can_read_own_document(ready_document, client):
    _, owner_headers, doc_id = ready_document
    resp = await client.get(f"/v1/documents/{doc_id}", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == doc_id


@pytest.mark.asyncio
async def test_tenant_cannot_edit_another_tenants_document(ready_document, client, make_tenant):
    _, _, doc_id = ready_document
    _, attacker_headers = await make_tenant()

    resp = await client.post(
        f"/v1/documents/{doc_id}/edits",
        json={"instruction": "delete everything"},
        headers={**attacker_headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_tenant_cannot_export_another_tenants_document(ready_document, client, make_tenant):
    _, _, doc_id = ready_document
    _, attacker_headers = await make_tenant()

    resp = await client.post(
        f"/v1/documents/{doc_id}/export",
        json={"format": "docx"},
        headers={**attacker_headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_tenant_cannot_poll_another_tenants_job(client, make_tenant, ready_document):
    owner_id, owner_headers, doc_id = ready_document
    # Owner starts an edit job.
    resp = await client.post(
        f"/v1/documents/{doc_id}/edits",
        json={"instruction": "add a clause"},
        headers={**owner_headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    job_id = resp.json()["job_id"]

    _, attacker_headers = await make_tenant()
    resp = await client.get(f"/v1/jobs/{job_id}", headers=attacker_headers)
    assert resp.status_code == 404
    # Owner can see it.
    resp_owner = await client.get(f"/v1/jobs/{job_id}", headers=owner_headers)
    assert resp_owner.status_code == 200
