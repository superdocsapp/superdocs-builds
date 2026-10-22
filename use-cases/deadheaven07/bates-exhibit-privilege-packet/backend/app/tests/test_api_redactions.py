"""API-level tests for the redaction pipeline (M-1, M-2, H-1).

Exercises detect/approve/apply/verify through the real routers, including
idempotent re-detection, invalid-UUID handling, and alphanumeric account
detection.
"""

import pytest
from qa_helpers import make_pdf

PII_LINES = [
    "Employee: Jane Smith",
    "SSN: 123-45-6789",
    "Email: jane.public@example.com",
    "Phone: (212) 555-0199",
    "Account: ACC-8821-4433",
    "Account spaced: ACC 8821 4433",
    "Account long: ACCOUNT-8821-4433",
    "Numeric account: 8821-4433-2211-9900",
    "Bates-like label: FQ-0500",
    "Date: 2026-08-14",
    "Page One",
    "Invoice: INV-2026-001",
]


async def _make_packet(client, name="Redaction QA Packet"):
    resp = await client.post(
        "/api/packets",
        json={
            "name": name,
            "bates_prefix": "RQ-",
            "bates_start_number": 500,
            "bates_padding": 4,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload_pii_doc(client, packet_id, lines=None):
    body = make_pdf(lines or PII_LINES)
    files = {"files": ("pii_evidence.pdf", body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()["documents"][0]["id"]


@pytest.fixture
async def packet_with_pii(superdocs_override):
    client, fake = superdocs_override
    packet_id = await _make_packet(client)
    doc_id = await _upload_pii_doc(client, packet_id)
    return client, fake, packet_id, doc_id


@pytest.mark.asyncio
async def test_detect_finds_account_and_pii_candidates(packet_with_pii):
    client, fake, packet_id, doc_id = packet_with_pii

    resp = await client.post(f"/api/redactions/{packet_id}/detect")
    assert resp.status_code == 200, resp.text
    assert resp.json()["documents_queued"] == 1

    resp = await client.get(f"/api/redactions/{packet_id}")
    assert resp.status_code == 200, resp.text
    candidates = resp.json()
    assert len(candidates) > 0

    matched = {c["matched_text"] for c in candidates}
    for expected in [
        "ACC-8821-4433",
        "ACC 8821 4433",
        "ACCOUNT-8821-4433",
        "8821-4433-2211-9900",
        "123-45-6789",
        "jane.public@example.com",
        "(212) 555-0199",
        "Jane Smith",
    ]:
        assert expected in matched, f"missing candidate {expected!r} in {sorted(matched)}"

    for not_expected in ["FQ-0500", "2026-08-14", "Page One", "INV-2026-001"]:
        assert not_expected not in matched, f"unexpected false positive {not_expected!r}"

    account = next(c for c in candidates if c["matched_text"] == "ACC-8821-4433")
    assert account["category"] == "account_number"
    assert account["page_number"] == 1

    doc_candidates = await client.get(f"/api/redactions/{packet_id}/{doc_id}")
    assert doc_candidates.status_code == 200
    assert len(doc_candidates.json()) == len(candidates)


@pytest.mark.asyncio
async def test_repeated_detect_is_idempotent(packet_with_pii):
    client, fake, packet_id, doc_id = packet_with_pii

    await client.post(f"/api/redactions/{packet_id}/detect")
    first = await client.get(f"/api/redactions/{packet_id}")
    first_count = len(first.json())

    await client.post(f"/api/redactions/{packet_id}/detect")
    second = await client.get(f"/api/redactions/{packet_id}")
    second_count = len(second.json())

    assert second_count == first_count, f"detect not idempotent: {first_count} -> {second_count}"

    audit = await client.get(f"/api/audit/{packet_id}")
    proposed = [e for e in audit.json()["events"] if e["event_type"] == "redaction_proposed"]
    assert len(proposed) == 2
    second_run = proposed[0]
    assert second_run["metadata"]["candidates_created"] == 0
    assert second_run["metadata"]["candidates_skipped"] == first_count


@pytest.mark.asyncio
async def test_approve_apply_verify_flow(packet_with_pii):
    client, fake, packet_id, doc_id = packet_with_pii

    await client.post(f"/api/redactions/{packet_id}/detect")
    candidates = (await client.get(f"/api/redactions/{packet_id}")).json()
    account = next(c for c in candidates if c["matched_text"] == "ACC-8821-4433")
    account_id = account["id"]

    approve = await client.post(
        f"/api/redactions/{account_id}/approve",
        json={"status": "approved", "approver": "qa-reviewer"},
    )
    assert approve.status_code == 200, approve.text

    apply = await client.post(f"/api/redactions/{account_id}/apply")
    assert apply.status_code == 200, apply.text
    assert apply.json()["status"] == "completed"

    applied = await client.get(f"/api/redactions/{packet_id}")
    applied_candidate = next(c for c in applied.json() if c["id"] == account_id)
    assert applied_candidate["status"] == "applied"
    assert applied_candidate["approval"]["approver"] == "qa-reviewer"

    audit = await client.get(f"/api/audit/{packet_id}")
    types = [e["event_type"] for e in audit.json()["events"]]
    assert "redaction_proposed" in types
    assert "redaction_approved" in types
    assert "redaction_applied" in types


@pytest.mark.asyncio
async def test_apply_requires_approval(packet_with_pii):
    client, fake, packet_id, doc_id = packet_with_pii

    await client.post(f"/api/redactions/{packet_id}/detect")
    candidate = (await client.get(f"/api/redactions/{packet_id}")).json()[0]

    resp = await client.post(f"/api/redactions/{candidate['id']}/apply")
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_apply_all_approved(packet_with_pii):
    client, fake, packet_id, doc_id = packet_with_pii

    await client.post(f"/api/redactions/{packet_id}/detect")
    candidates = (await client.get(f"/api/redactions/{packet_id}")).json()
    for candidate in candidates:
        resp = await client.post(
            f"/api/redactions/{candidate['id']}/approve",
            json={"status": "approved", "approver": "qa-reviewer"},
        )
        assert resp.status_code == 200, resp.text

    resp = await client.post(
        f"/api/redactions/{packet_id}/apply-all",
        json={"document_ids": [doc_id]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["candidates_applied"] == len(candidates)

    verified = (await client.get(f"/api/redactions/{packet_id}")).json()
    assert all(c["status"] == "applied" for c in verified)

    audit = await client.get(f"/api/audit/{packet_id}")
    types = [e["event_type"] for e in audit.json()["events"]]
    assert types.count("redaction_applied") == len(candidates)


@pytest.mark.asyncio
async def test_detect_invalid_uuid_422(api_client):
    client = api_client
    resp = await client.post("/api/redactions/not-a-uuid/detect")
    assert resp.status_code == 422, resp.text

    resp = await client.get("/api/redactions/not-a-uuid")
    assert resp.status_code == 422, resp.text

    resp = await client.get("/api/redactions/not-a-uuid/not-a-uuid")
    assert resp.status_code == 422, resp.text

    resp = await client.post(
        "/api/redactions/not-a-uuid/approve", json={"status": "approved", "approver": "qa"}
    )
    assert resp.status_code == 422, resp.text

    resp = await client.post("/api/redactions/not-a-uuid/apply")
    assert resp.status_code == 422, resp.text

    resp = await client.post("/api/redactions/not-a-uuid/apply-all", json={"document_ids": []})
    assert resp.status_code == 422, resp.text

    resp = await client.post(
        f"/api/redactions/{'00000000-0000-0000-0000-000000000000'}/apply-all",
        json={"document_ids": ["not-a-uuid"]},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_missing_resources_404(api_client):
    client = api_client
    missing = "00000000-0000-0000-0000-000000000001"
    resp = await client.post(f"/api/redactions/{missing}/detect")
    assert resp.status_code == 404, resp.text
    resp = await client.get(f"/api/redactions/{missing}")
    assert resp.status_code == 404, resp.text
    resp = await client.post(
        f"/api/redactions/{missing}/approve", json={"status": "approved", "approver": "qa"}
    )
    assert resp.status_code == 404, resp.text
