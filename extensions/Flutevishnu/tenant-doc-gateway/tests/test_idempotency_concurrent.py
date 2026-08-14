"""CONCURRENT idempotency proof (the important one).

Fires TWO identical requests at the SAME Idempotency-Key simultaneously via
asyncio.gather and asserts that exactly ONE job/record was actually created — not
a sequential retry test, a real race.

Why this passes: the idempotency layer INSERTS first and lets the DB's
UNIQUE(tenant_id, key) constraint pick the single winner; the loser replays the
winner's response instead of creating a second job. (See services/idempotency.py.)
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from tests.helpers import count_documents, count_jobs


@pytest.mark.asyncio
async def test_two_concurrent_identical_requests_create_one_record(client, make_tenant, sessionmaker):
    tenant_id, headers = await make_tenant()
    key = uuid.uuid4().hex

    def _post():
        # Fresh file tuple per request (streams are single-use).
        files = {"file": ("race.docx", b"identical body bytes", "application/octet-stream")}
        return client.post("/v1/documents", files=files, headers={**headers, "Idempotency-Key": key})

    # Fire both at once.
    r1, r2 = await asyncio.gather(_post(), _post())

    # Exactly one document and one job exist for this tenant — the race did NOT
    # double-create.
    assert await count_documents(sessionmaker, tenant_id) == 1
    assert await count_jobs(sessionmaker, tenant_id) == 1

    # Both callers get a sensible response; any success/replay shares one id.
    statuses = {r1.status_code, r2.status_code}
    assert statuses.issubset({202, 200, 409})

    doc_ids = {
        r.json()["document"]["id"]
        for r in (r1, r2)
        if r.status_code in (200, 202) and "document" in r.json()
    }
    assert len(doc_ids) == 1  # never two different documents
