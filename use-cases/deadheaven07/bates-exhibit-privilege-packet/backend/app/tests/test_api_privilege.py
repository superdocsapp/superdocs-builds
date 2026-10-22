"""API-level tests for privilege marking (C-1 regression).

Covers the routers directly through the FastAPI application, exercising
POST/PATCH /api/privilege/{packet_id}/{document_id} plus list/log endpoints.
"""

import pytest
from qa_helpers import make_pdf


async def _make_packet(client, name="Privilege QA Packet", start=1):
    resp = await client.post(
        "/api/packets",
        json={
            "name": name,
            "bates_prefix": "PV-",
            "bates_start_number": start,
            "bates_padding": 4,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload_pdf(client, packet_id, filename="evidence.pdf"):
    body = make_pdf(["Evidence page one", "Evidence page two"], page_count=2)
    files = {"files": (filename, body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()["documents"][0]["id"]


@pytest.mark.asyncio
async def test_privilege_post_marks_document(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    doc_id = await _upload_pdf(client, packet_id)

    resp = await client.post(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": "privileged",
            "category": "attorney_client",
            "reason": "Attorney-client privileged communication",
            "reviewer": "qa-reviewer",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "privileged"
    assert data["category"] == "attorney_client"
    assert data["document_id"] == doc_id

    listing = await client.get(f"/api/privilege/{packet_id}")
    assert listing.status_code == 200
    decisions = listing.json()
    assert len(decisions) == 1
    assert decisions[0]["status"] == "privileged"

    log = await client.get(f"/api/privilege/{packet_id}/log")
    assert log.status_code == 200
    log_data = log.json()
    assert log_data["total_privileged_documents"] == 1
    assert log_data["entries"][0]["document_id"] == doc_id


@pytest.mark.asyncio
async def test_privilege_post_work_product(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    doc_id = await _upload_pdf(client, packet_id)

    resp = await client.post(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": "privileged",
            "category": "work_product",
            "reason": "Litigation work product",
            "reviewer": "qa-reviewer",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["category"] == "work_product"


@pytest.mark.asyncio
async def test_privilege_patch_overrides_existing_decision(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    doc_id = await _upload_pdf(client, packet_id)

    first = await client.post(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": "privileged",
            "category": "attorney_client",
            "reason": "Initial reason",
            "reviewer": "qa-reviewer",
        },
    )
    assert first.status_code == 200, first.text

    override = await client.patch(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": "privileged",
            "category": "work_product",
            "reason": "Override reason",
            "reviewer": "qa-reviewer",
        },
    )
    assert override.status_code == 200, override.text
    data = override.json()
    assert data["category"] == "work_product"
    assert data["reason"] == "Override reason"

    confirm = await client.patch(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": "not_privileged",
            "category": None,
            "reason": None,
            "reviewer": "qa-reviewer",
        },
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "not_privileged"

    listing = await client.get(f"/api/privilege/{packet_id}")
    assert len(listing.json()) == 1, "override must not create duplicate decisions"


@pytest.mark.asyncio
async def test_privilege_wrong_packet_404(api_client):
    client = api_client
    packet_a = await _make_packet(client, name="Packet A")
    packet_b = await _make_packet(client, name="Packet B")
    doc_id = await _upload_pdf(client, packet_a)

    resp = await client.post(
        f"/api/privilege/{packet_b}/{doc_id}",
        json={"status": "privileged", "reason": "r", "reviewer": "qa"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_privilege_missing_document_404(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    missing = "00000000-0000-0000-0000-000000000001"

    resp = await client.post(
        f"/api/privilege/{packet_id}/{missing}",
        json={"status": "privileged", "reason": "r", "reviewer": "qa"},
    )
    assert resp.status_code == 404, resp.text

    resp = await client.patch(
        f"/api/privilege/{packet_id}/{missing}",
        json={"status": "privileged", "reason": "r", "reviewer": "qa"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_privilege_missing_packet_404(api_client):
    client = api_client
    missing = "00000000-0000-0000-0000-000000000002"

    resp = await client.post(
        f"/api/privilege/{missing}/{missing}",
        json={"status": "privileged", "reason": "r", "reviewer": "qa"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_privilege_invalid_uuid_422(api_client):
    client = api_client
    resp = await client.post(
        "/api/privilege/not-a-uuid/not-a-uuid",
        json={"status": "privileged", "reason": "r", "reviewer": "qa"},
    )
    assert resp.status_code == 422, resp.text

    resp = await client.get("/api/privilege/not-a-uuid")
    assert resp.status_code == 422, resp.text

    resp = await client.get("/api/privilege/not-a-uuid/log")
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_privilege_reason_required_400(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    doc_id = await _upload_pdf(client, packet_id)

    resp = await client.post(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": "privileged",
            "category": "attorney_client",
            "reason": None,
            "reviewer": "qa",
        },
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_privilege_invalid_status_422(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    doc_id = await _upload_pdf(client, packet_id)

    resp = await client.post(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={"status": "not_a_status", "reviewer": "qa"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_privilege_emits_audit_events(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    doc_id = await _upload_pdf(client, packet_id)

    await client.post(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": "privileged",
            "category": "attorney_client",
            "reason": "r",
            "reviewer": "qa-audit",
        },
    )
    await client.patch(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": "privileged",
            "category": "work_product",
            "reason": "r2",
            "reviewer": "qa-audit",
        },
    )

    resp = await client.get(f"/api/audit/{packet_id}")
    assert resp.status_code == 200, resp.text
    events = resp.json()["events"]
    marked = [e for e in events if e["event_type"] == "privilege_marked"]
    assert len(marked) == 2, marked
    actions = {e["metadata"]["action"] for e in marked}
    assert actions == {"created", "updated"}, marked
    assert all(e["user_id"] == "qa-audit" for e in marked)
