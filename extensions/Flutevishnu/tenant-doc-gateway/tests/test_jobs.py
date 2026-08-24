"""End-to-end job flow: edit -> awaiting approval, and export -> succeeded."""

from __future__ import annotations

import uuid

import pytest

from app.services.job_runner import run_job


@pytest.mark.asyncio
async def test_edit_job_produces_pending_changes(ready_document, client, fake_superdocs, sessionmaker, settings, queue_recorder):
    _, headers, doc_id = ready_document

    resp = await client.post(
        f"/v1/documents/{doc_id}/edits",
        json={"instruction": "add a confidentiality clause"},
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    # The API enqueued exactly one job for the worker.
    assert uuid.UUID(job_id) in queue_recorder.enqueued

    # Run the worker logic (as the Arq worker would).
    await run_job(
        uuid.UUID(job_id), sessionmaker=sessionmaker, superdocs=fake_superdocs, settings=settings, poll_interval=0
    )

    poll = await client.get(f"/v1/jobs/{job_id}", headers=headers)
    assert poll.status_code == 200
    assert poll.json()["status"] == "awaiting_approval"
    assert poll.json()["ops_cost"] == 1.0

    changes = await client.get(f"/v1/documents/{doc_id}/proposed-changes", headers=headers)
    assert changes.status_code == 200
    assert len(changes.json()["proposed_changes"]) == 2


@pytest.mark.asyncio
async def test_export_job_succeeds(ready_document, client, fake_superdocs, sessionmaker, settings):
    _, headers, doc_id = ready_document

    resp = await client.post(
        f"/v1/documents/{doc_id}/export",
        json={"format": "pdf"},
        headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    await run_job(
        uuid.UUID(job_id), sessionmaker=sessionmaker, superdocs=fake_superdocs, settings=settings, poll_interval=0
    )

    poll = await client.get(f"/v1/jobs/{job_id}", headers=headers)
    assert poll.status_code == 200
    body = poll.json()
    assert body["status"] == "succeeded"
    assert body["result"]["download_url"].endswith(".pdf")
