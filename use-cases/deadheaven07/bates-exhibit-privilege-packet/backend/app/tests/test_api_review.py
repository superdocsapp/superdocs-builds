"""API-level tests for the SuperDocs AI review flow (L-4, M-3).

Verifies analyze/poll/approve/export endpoints, provider error translation,
session reuse, and AI_ANALYSIS_FAILED audit events through the real routers
with a mocked SuperDocs adapter.
"""

import httpx
import pytest

from qa_helpers import make_pdf


async def _make_packet(client, name="Review QA Packet"):
    resp = await client.post("/api/packets", json={
        "name": name, "bates_prefix": "RV-", "bates_start_number": 1, "bates_padding": 4,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload(client, packet_id):
    files = {"files": ("review_evidence.pdf", make_pdf(["Review evidence"]), "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()["documents"][0]["id"]


async def _events(client, packet_id):
    resp = await client.get(f"/api/audit/{packet_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


@pytest.fixture
def review_service(api_client, mock_superdocs_adapter):
    from app.main import app
    from app.services.superdocs_integration import (
        SuperDocsIntegrationService,
        get_superdocs_service,
    )

    service = SuperDocsIntegrationService(adapter=mock_superdocs_adapter)
    app.dependency_overrides[get_superdocs_service] = lambda: service
    yield api_client, mock_superdocs_adapter
    app.dependency_overrides.pop(get_superdocs_service, None)


async def _analyze(client, packet_id, doc_id, instruction="Summarize this document"):
    resp = await client.post(
        f"/api/review/{packet_id}/documents/{doc_id}/analyze",
        json={"instruction": instruction},
    )
    return resp


@pytest.mark.asyncio
async def test_analyze_starts_job_and_persists_session(review_service):
    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)

    resp = await _analyze(client, packet_id, doc_id)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["job_id"] == "test-job"

    adapter.upload_document.assert_awaited_once()
    adapter.chat_async.assert_awaited_once()

    docs = await client.get(f"/api/documents/{packet_id}")
    doc = next(d for d in docs.json() if d["id"] == doc_id)
    assert doc["status"] == "ai_analysis"

    events = await _events(client, packet_id)
    started = [e for e in events if e["event_type"] == "ai_analysis_started"]
    assert len(started) == 1
    assert started[0]["metadata"]["job_id"] == "test-job"


@pytest.mark.asyncio
async def test_analyze_reuses_existing_session(review_service):
    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)

    await _analyze(client, packet_id, doc_id)
    assert adapter.upload_document.await_count == 1

    poll = await client.get(
        f"/api/review/{packet_id}/documents/{doc_id}/analysis-status",
        params={"job_id": "test-job"},
    )
    assert poll.status_code == 200, poll.text
    assert poll.json()["status"] == "completed"

    resp = await _analyze(client, packet_id, doc_id, instruction="Summarize again")
    assert resp.status_code == 200, resp.text

    assert adapter.upload_document.await_count == 1, "document must not be re-uploaded"
    assert adapter.chat_async.await_count == 2


@pytest.mark.asyncio
async def test_poll_completed_marks_document_completed(review_service):
    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)
    await _analyze(client, packet_id, doc_id)

    resp = await client.get(
        f"/api/review/{packet_id}/documents/{doc_id}/analysis-status",
        params={"job_id": "test-job"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"

    docs = await client.get(f"/api/documents/{packet_id}")
    doc = next(d for d in docs.json() if d["id"] == doc_id)
    assert doc["status"] == "completed"

    events = await _events(client, packet_id)
    completed = [e for e in events if e["event_type"] == "ai_analysis_completed"]
    assert len(completed) == 1


@pytest.mark.asyncio
async def test_poll_awaiting_approval_returns_proposed_changes(review_service):
    from unittest.mock import AsyncMock
    from app.services.superdocs_port import JobStatus, ProposedChangeBatch, ProposedChange

    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)
    await _analyze(client, packet_id, doc_id)

    adapter.poll_job = AsyncMock(return_value=JobStatus(
        job_id="test-job",
        status="awaiting_approval",
        result={},
        metadata={"pending_changes": {"html": "x"}},
    ))
    adapter.parse_proposed_change_batch = lambda content: ProposedChangeBatch(
        batch_id="batch-1",
        batch_total=1,
        changes=[
            ProposedChange(
                change_id="c1",
                operation="replace",
                chunk_id="chunk-3",
                old_html="<p>old</p>",
                new_html="<p>new</p>",
                ai_explanation="Rewrite",
                insert_after_chunk_id=None,
            )
        ],
    )

    resp = await client.get(
        f"/api/review/{packet_id}/documents/{doc_id}/analysis-status",
        params={"job_id": "test-job"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["status"] == "awaiting_approval"
    assert payload["changes"][0]["change_id"] == "c1"

    docs = await client.get(f"/api/documents/{packet_id}")
    doc = next(d for d in docs.json() if d["id"] == doc_id)
    assert doc["status"] == "waiting_review"


@pytest.mark.asyncio
async def test_approve_changes_completes_document(review_service):
    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)
    await _analyze(client, packet_id, doc_id)

    resp = await client.post(
        f"/api/review/{packet_id}/documents/{doc_id}/approve-changes",
        json={"job_id": "test-job", "approved": True, "changes": [{"change_id": "c1"}]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "completed"

    docs = await client.get(f"/api/documents/{packet_id}")
    doc = next(d for d in docs.json() if d["id"] == doc_id)
    assert doc["status"] == "completed"

    events = await _events(client, packet_id)
    assert any(e["event_type"] == "change_approved" for e in events)
    assert any(e["event_type"] == "ai_analysis_completed" for e in events)


@pytest.mark.asyncio
async def test_analyze_upstream_415_maps_to_415_not_500(review_service):
    from app.services.superdocs_adapter import SuperDocsAPIError

    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)

    adapter.chat_async.side_effect = SuperDocsAPIError(
        "Unsupported media type", status_code=415, response_body="<raw body with secrets>"
    )

    resp = await _analyze(client, packet_id, doc_id)
    assert resp.status_code == 415, resp.text
    assert "rejected" in resp.json()["detail"]
    assert "<raw body" not in str(resp.json())

    events = await _events(client, packet_id)
    failed = [e for e in events if e["event_type"] == "ai_analysis_failed"]
    assert len(failed) == 1
    assert failed[0]["metadata"]["error"] == "SuperDocsAPIError"

    docs = await client.get(f"/api/documents/{packet_id}")
    doc = next(d for d in docs.json() if d["id"] == doc_id)
    assert doc["status"] == "completed", "document must not be left stuck"


@pytest.mark.asyncio
async def test_analyze_upstream_500_maps_to_502(review_service):
    from app.services.superdocs_adapter import SuperDocsAPIError

    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)

    adapter.chat_async.side_effect = SuperDocsAPIError("boom", status_code=500)

    resp = await _analyze(client, packet_id, doc_id)
    assert resp.status_code == 502, resp.text


@pytest.mark.asyncio
async def test_analyze_network_error_maps_to_504(review_service):
    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)

    adapter.chat_async.side_effect = httpx.ConnectTimeout("upstream unreachable")

    resp = await _analyze(client, packet_id, doc_id)
    assert resp.status_code == 504, resp.text

    events = await _events(client, packet_id)
    assert any(e["event_type"] == "ai_analysis_failed" for e in events)


@pytest.mark.asyncio
async def test_analyze_generic_error_maps_to_500(review_service):
    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)

    adapter.chat_async.side_effect = RuntimeError("unexpected internal failure")

    resp = await _analyze(client, packet_id, doc_id)
    assert resp.status_code == 500, resp.text
    assert "internal" not in str(resp.json()["detail"]).lower()


@pytest.mark.asyncio
async def test_export_document(review_service):
    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)
    await _analyze(client, packet_id, doc_id)

    resp = await client.post(
        f"/api/review/{packet_id}/documents/{doc_id}/export",
        json={"format": "pdf"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["download_url"] == "https://example.com/download"


@pytest.mark.asyncio
async def test_analyze_requires_processed_document(review_service):
    client, adapter = review_service
    resp = await client.post(
        f"/api/review/{'00000000-0000-0000-0000-000000000001'}/documents/"
        f"{'00000000-0000-0000-0000-000000000002'}/analyze",
        json={"instruction": "x"},
    )
    assert resp.status_code == 404, resp.text

    resp = await client.post(
        f"/api/review/not-a-uuid/documents/{'00000000-0000-0000-0000-000000000002'}/analyze",
        json={"instruction": "x"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_document_history_endpoint(review_service):
    client, adapter = review_service
    packet_id = await _make_packet(client)
    doc_id = await _upload(client, packet_id)
    await _analyze(client, packet_id, doc_id)

    resp = await client.get(f"/api/review/{packet_id}/documents/{doc_id}/history")
    assert resp.status_code == 200, resp.text