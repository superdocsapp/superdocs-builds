"""Sequential idempotency: retries replay; key reuse with a different body 409s."""

from __future__ import annotations

import uuid

import pytest

from tests.helpers import count_documents, count_jobs


@pytest.mark.asyncio
async def test_retry_replays_same_result(client, make_tenant, sessionmaker):
    tenant_id, headers = await make_tenant()
    key = uuid.uuid4().hex
    files = {"file": ("a.docx", b"same bytes", "application/octet-stream")}

    r1 = await client.post("/v1/documents", files=files, headers={**headers, "Idempotency-Key": key})
    files = {"file": ("a.docx", b"same bytes", "application/octet-stream")}
    r2 = await client.post("/v1/documents", files=files, headers={**headers, "Idempotency-Key": key})

    assert r1.status_code == 202
    assert r2.status_code == 202
    # Same document + job returned; the second call did not create anything new.
    assert r1.json()["document"]["id"] == r2.json()["document"]["id"]
    assert r1.json()["job"]["job_id"] == r2.json()["job"]["job_id"]
    assert await count_documents(sessionmaker, tenant_id) == 1
    assert await count_jobs(sessionmaker, tenant_id) == 1


@pytest.mark.asyncio
async def test_same_key_different_body_conflicts(ready_document, client):
    _, headers, doc_id = ready_document
    key = uuid.uuid4().hex

    r1 = await client.post(
        f"/v1/documents/{doc_id}/edits",
        json={"instruction": "first instruction"},
        headers={**headers, "Idempotency-Key": key},
    )
    assert r1.status_code == 202

    # Same key, different body -> 409 (never a silent wrong replay).
    r2 = await client.post(
        f"/v1/documents/{doc_id}/edits",
        json={"instruction": "COMPLETELY different instruction"},
        headers={**headers, "Idempotency-Key": key},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_missing_idempotency_key_rejected(ready_document, client):
    _, headers, doc_id = ready_document
    resp = await client.post(
        f"/v1/documents/{doc_id}/edits",
        json={"instruction": "no key provided"},
        headers=headers,
    )
    assert resp.status_code == 400
