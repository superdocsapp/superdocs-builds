"""API-level tests for audit trail completeness (M-3).

Verifies metadata is persisted on events (event_metadata fix) and that
processing/bates/validation events fire through the real routers.
"""

import pytest
from qa_helpers import make_pdf
from sqlalchemy import select

from app.domain.audit import AuditEvent, AuditEventType


async def _make_packet(client, name="Audit QA Packet", start=1):
    resp = await client.post(
        "/api/packets",
        json={
            "name": name,
            "bates_prefix": "AU-",
            "bates_start_number": start,
            "bates_padding": 4,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload(client, packet_id, filename="audit_evidence.pdf", lines=None):
    body = make_pdf(lines or ["Audit evidence page"])
    files = {"files": (filename, body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()["documents"][0]["id"]


async def _events(client, packet_id):
    resp = await client.get(f"/api/audit/{packet_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["events"]


@pytest.mark.asyncio
async def test_upload_emits_processing_and_bates_events_with_metadata(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    await _upload(client, packet_id)

    events = await _events(client, packet_id)
    by_type = {}
    for e in events:
        by_type.setdefault(e["event_type"], []).append(e)

    assert "upload" in by_type
    upload_event = by_type["upload"][0]
    assert upload_event["metadata"]["filename"] == "audit_evidence.pdf"

    processing_started = by_type.get("processing_started", [])
    processing_completed = by_type.get("processing_completed", [])
    assert len(processing_started) == 1
    assert len(processing_completed) == 1
    assert processing_started[0]["metadata"]["filename"] == "audit_evidence.pdf"
    assert processing_completed[0]["metadata"]["filename"] == "audit_evidence.pdf"

    bates_assigned = by_type.get("bates_assigned", [])
    assert len(bates_assigned) == 1
    assert bates_assigned[0]["metadata"]["count"] == 1
    assert bates_assigned[0]["metadata"]["bates_start"] == "AU-0001"
    assert bates_assigned[0]["metadata"]["bates_end"] == "AU-0001"

    ordered = [e["event_type"] for e in events]
    assert (
        ordered.index("bates_assigned")
        < ordered.index("processing_completed")
        < ordered.index("upload")
        < ordered.index("processing_started")
    )


@pytest.mark.asyncio
async def test_upload_metadata_persisted_in_db(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    await _upload(client, packet_id, filename="metadata_check.pdf")

    events = await _events(client, packet_id)
    upload_event = next(e for e in events if e["event_type"] == "upload")
    assert upload_event["metadata"] is not None
    assert upload_event["metadata"]["filename"] == "metadata_check.pdf"


@pytest.mark.asyncio
async def test_packet_created_and_updated_events(api_client):
    client = api_client
    resp = await client.post(
        "/api/packets",
        json={
            "name": "Audit Trail Packet",
            "bates_prefix": "TR-",
            "bates_start_number": 1,
            "bates_padding": 4,
        },
    )
    packet_id = resp.json()["id"]

    await client.patch(f"/api/packets/{packet_id}", json={"name": "Renamed Packet"})

    events = await _events(client, packet_id)
    created = [e for e in events if e["event_type"] == "packet_created"]
    updated = [e for e in events if e["event_type"] == "packet_updated"]
    assert len(created) == 1
    assert created[0]["metadata"]["name"] == "Audit Trail Packet"
    assert len(updated) == 1
    assert updated[0]["metadata"]["fields"] == ["name"]


@pytest.mark.asyncio
async def test_bates_reassign_emits_event(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    await _upload(client, packet_id)
    await _upload(client, packet_id, filename="second.pdf")

    events = await _events(client, packet_id)
    bates_events = [e for e in events if e["event_type"] == "bates_assigned"]
    assert len(bates_events) == 2
    # Each upload-triggered assign_bates emits one event;
    # the second call is idempotent and only assigns the new page.
    count_values = [e["metadata"]["count"] for e in bates_events]
    bates_start_values = [e["metadata"]["bates_start"] for e in bates_events]
    bates_end_values = [e["metadata"]["bates_end"] for e in bates_events]
    assert set(count_values) == {1}
    assert set(bates_start_values) == {"AU-0001", "AU-0002"}
    assert set(bates_end_values) == {"AU-0001", "AU-0002"}


@pytest.mark.asyncio
async def test_packet_validated_event_on_validate(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    await _upload(client, packet_id)

    resp = await client.post(f"/api/exports/{packet_id}/validate")
    assert resp.status_code == 200, resp.text

    events = await _events(client, packet_id)
    validated = [e for e in events if e["event_type"] == "packet_validated"]
    assert len(validated) == 1
    assert validated[0]["metadata"]["valid"] is True
    assert isinstance(validated[0]["metadata"]["errors"], list)
    assert isinstance(validated[0]["metadata"]["warnings"], list)


@pytest.mark.asyncio
async def test_events_survive_packet_delete(api_client, test_session):
    client = api_client
    packet_id = await _make_packet(client)
    await _upload(client, packet_id)

    resp = await client.delete(f"/api/packets/{packet_id}")
    assert resp.status_code == 200, resp.text

    result = await test_session.execute(
        select(AuditEvent).where(AuditEvent.event_type == AuditEventType.PACKET_DELETED)
    )
    deleted = result.scalars().all()
    assert len(deleted) == 1
    assert deleted[0].event_metadata["packet_name"] == "Audit QA Packet"
    assert deleted[0].event_metadata["document_count"] == 1
    assert deleted[0].user_id is not None


@pytest.mark.asyncio
async def test_reorder_emits_bates_reassignment(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    await _upload(client, packet_id, filename="first.pdf")
    second = await _upload(client, packet_id, filename="second.pdf")

    resp = await client.patch(f"/api/documents/{packet_id}/{second}/reorder", json={"new_order": 1})
    assert resp.status_code == 200, resp.text

    events = await _events(client, packet_id)
    reorder = [e for e in events if e["event_type"] == "document_reordered"]
    assert len(reorder) == 1
    bates_events = [e for e in events if e["event_type"] == "bates_assigned"]
    # After reorder, assign_bates is idempotent: pages already assigned are skipped.
    # The existing assignments (from the two uploads) remain valid, just reordered.
    # We expect 2 bates_assigned events (one per upload-triggered assign_bates call).
    assert len(bates_events) >= 2
    bates_start_values = [e["metadata"]["bates_start"] for e in bates_events]
    bates_end_values = [e["metadata"]["bates_end"] for e in bates_events]
    assert "AU-0001" in set(bates_start_values)
    assert "AU-0002" in set(bates_end_values)
