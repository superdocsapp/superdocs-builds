"""Per-item approval: rejecting ONE change does not discard the others."""

from __future__ import annotations

import uuid

import pytest

from app.services.job_runner import run_job


async def _start_edit_with_two_changes(client, headers, doc_id, fake_superdocs, sessionmaker, settings):
    resp = await client.post(
        f"/v1/documents/{doc_id}/edits",
        json={"instruction": "make two edits"},
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    job_id = resp.json()["job_id"]
    await run_job(
        uuid.UUID(job_id), sessionmaker=sessionmaker, superdocs=fake_superdocs, settings=settings, poll_interval=0
    )
    listing = await client.get(f"/v1/documents/{doc_id}/proposed-changes", headers=headers)
    return listing.json()["proposed_changes"]


@pytest.mark.asyncio
async def test_reject_one_keeps_the_rest(ready_document, client, fake_superdocs, sessionmaker, settings):
    _, headers, doc_id = ready_document
    changes = await _start_edit_with_two_changes(client, headers, doc_id, fake_superdocs, sessionmaker, settings)
    assert len(changes) == 2
    first, second = changes[0], changes[1]

    # Reject the first item.
    reject = await client.post(
        f"/v1/documents/{doc_id}/proposed-changes/{first['id']}/decision",
        json={"approved": False, "feedback": "not this one"},
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    # The OTHER change is untouched and still pending.
    still_pending = await client.get(f"/v1/documents/{doc_id}/proposed-changes", headers=headers)
    pending = still_pending.json()["proposed_changes"]
    assert len(pending) == 1
    assert pending[0]["id"] == second["id"]
    assert pending[0]["status"] == "pending"

    # Approve the remaining one.
    approve = await client.post(
        f"/v1/documents/{doc_id}/proposed-changes/{second['id']}/decision",
        json={"approved": True},
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    # Both decisions were forwarded to SuperDocs, one reject + one approve.
    forwarded = {(c["change_id"], c["approved"]) for c in fake_superdocs.decide_calls}
    assert ("c1", False) in forwarded
    assert ("c2", True) in forwarded


@pytest.mark.asyncio
async def test_deciding_twice_conflicts(ready_document, client, fake_superdocs, sessionmaker, settings):
    _, headers, doc_id = ready_document
    changes = await _start_edit_with_two_changes(client, headers, doc_id, fake_superdocs, sessionmaker, settings)
    change_id = changes[0]["id"]

    first = await client.post(
        f"/v1/documents/{doc_id}/proposed-changes/{change_id}/decision",
        json={"approved": True},
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert first.status_code == 200

    # A DIFFERENT idempotency key but the item is already decided -> 409.
    second = await client.post(
        f"/v1/documents/{doc_id}/proposed-changes/{change_id}/decision",
        json={"approved": False},
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert second.status_code == 409
