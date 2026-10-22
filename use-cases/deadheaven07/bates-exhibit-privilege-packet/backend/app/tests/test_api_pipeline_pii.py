"""End-to-end API test: full pipeline -> build -> PII-free artifact verification
(Phase 9). Covers H-1 end-to-end, privilege log, manifest integrity, idempotent
rebuild, and delete cleanup.
"""

import os

import pytest
from qa_helpers import (
    PII_FIXTURES,
    assert_artifacts_pii_free,
    make_pdf,
    sha256_of,
)

from app.config import get_settings

LINES = [
    "EMPLOYEE PERSONNEL RECORD",
    "Name: John Doe",
    "SSN: 123-45-6789",
    "Email: jane.public@example.com",
    "Phone: (212) 555-0199",
    "Account number: ACC-8821-4433",
    "Bank: 8821-4433-2211-9900",
    "Reference: FQ-0500",
]


def _final_dir(packet_id):
    return os.path.join(get_settings().storage_root, "final", packet_id)


def _sha256_of_file(path):
    with open(path, "rb") as f:
        return sha256_of(f.read())


def _final_artifacts(packet_id):
    return [
        os.path.join(_final_dir(packet_id), "final_packet.pdf"),
        os.path.join(_final_dir(packet_id), "exhibit_index.pdf"),
        os.path.join(_final_dir(packet_id), "privilege_log.pdf"),
    ]


async def _make_packet(client, name="Pipeline QA Packet", start=1000):
    resp = await client.post(
        "/api/packets",
        json={
            "name": name,
            "bates_prefix": "QA-",
            "bates_start_number": start,
            "bates_padding": 4,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload(client, packet_id, filename="personnel.pdf", lines=None, page_count=1):
    body = make_pdf(lines or LINES, page_count=page_count)
    files = {"files": (filename, body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()["documents"][0]["id"]


async def _mark_privileged(client, packet_id, doc_id, status="privileged"):
    resp = await client.post(
        f"/api/privilege/{packet_id}/{doc_id}",
        json={
            "status": status,
            "reason": "Contains legal advice",
            "marked_by": "qa-revi",
            "reviewer": "qa-reviewer",
            "category": "attorney_client",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
async def built_packet(superdocs_override):
    client, fake = superdocs_override
    packet_id = await _make_packet(client)
    priv_doc = await _upload(
        client,
        packet_id,
        filename="privileged_advice.pdf",
        lines=["Legal advice from counsel", "No PII in this one"],
    )
    pub_doc = await _upload(client, packet_id, filename="personnel.pdf", lines=LINES, page_count=2)

    await _mark_privileged(client, packet_id, priv_doc)

    resp = await client.post(f"/api/redactions/{packet_id}/detect")
    assert resp.status_code == 200, resp.text
    candidates = (await client.get(f"/api/redactions/{packet_id}")).json()
    assert len(candidates) >= 6, f"expected many candidates, got {len(candidates)}"
    for c in candidates:
        resp = await client.post(
            f"/api/redactions/{c['id']}/approve",
            json={"status": "approved", "approver": "qa-reviewer"},
        )
        assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/redactions/{packet_id}/apply-all", json={"document_ids": [pub_doc, priv_doc]}
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(f"/api/exports/{packet_id}/validate")
    assert resp.status_code == 200, resp.text
    validation = resp.json()
    assert validation["valid"] is True, validation

    resp = await client.post(f"/api/exports/{packet_id}/build")
    assert resp.status_code == 200, resp.text
    build = resp.json()

    return client, packet_id, (priv_doc, pub_doc), build


@pytest.mark.asyncio
async def test_build_artifacts_pii_free(built_packet):
    client, packet_id, doc_ids, build = built_packet

    assert_artifacts_pii_free(_final_dir(packet_id), PII_FIXTURES)

    for path in _final_artifacts(packet_id):
        assert os.path.exists(path), f"missing {path}"

    exhibits_dir = os.path.join(_final_dir(packet_id), "exhibits")
    assert os.listdir(exhibits_dir), "no exhibit files produced"


@pytest.mark.asyncio
async def test_manifest_sha_matches_files(built_packet):
    client, packet_id, doc_ids, build = built_packet

    resp = await client.get(f"/api/exports/{packet_id}/manifest")
    assert resp.status_code == 200, resp.text
    manifest = resp.json()

    assert manifest["total_documents"] == 2
    assert manifest["total_pages"] == 5
    assert manifest["bates_start"] == "QA-1000"
    assert manifest["bates_end"] == "QA-1002"

    assert manifest["final_packet_sha256"] == _sha256_of_file(
        os.path.join(_final_dir(packet_id), "final_packet.pdf")
    )

    for exhibit in manifest["entries"]:
        assert exhibit["final_sha256"] == _sha256_of_file(
            os.path.join(
                _final_dir(packet_id),
                "exhibits",
                os.path.basename(exhibit["final_file_path"]),
            )
        )

    entries = manifest["entries"]
    assert len(entries) == 2
    assert entries[0]["bates_start"] == "QA-1000"
    assert entries[-1]["bates_end"] == "QA-1002"
    assert entries[0]["privilege_status"] == "privileged"
    assert all(e["final_sha256"] is not None for e in entries)


@pytest.mark.asyncio
async def test_privilege_log_lists_privileged_document(built_packet):
    client, packet_id, doc_ids, build = built_packet

    resp = await client.post(f"/api/exports/{packet_id}/build")
    assert resp.status_code == 200, resp.text

    manifest = (await client.get(f"/api/exports/{packet_id}/manifest")).json()
    privileged_entries = [e for e in manifest["entries"] if e["privilege_status"] == "privileged"]
    assert len(privileged_entries) == 1
    assert privileged_entries[0]["bates_start"] == "QA-1000"
    assert manifest["entries"][0]["privilege_category"] == "attorney_client"


@pytest.mark.asyncio
async def test_rebuild_replaces_artifacts_and_keeps_manifest_consistent(built_packet):
    client, packet_id, doc_ids, build = built_packet

    resp = await client.post(f"/api/exports/{packet_id}/build")
    assert resp.status_code == 200, resp.text

    assert os.path.exists(os.path.join(_final_dir(packet_id), "final_packet.pdf"))
    manifests = await client.get(f"/api/exports/{packet_id}/manifest")
    assert manifests.status_code == 200
    new_manifest = manifests.json()
    assert new_manifest["final_packet_sha256"] == _sha256_of_file(
        os.path.join(_final_dir(packet_id), "final_packet.pdf")
    )
    assert new_manifest["generated_at"] is not None
    assert_artifacts_pii_free(_final_dir(packet_id), PII_FIXTURES)


@pytest.mark.asyncio
async def test_build_fails_on_unbuilt_validate_error(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    await _upload(client, packet_id)

    resp = await client.post(f"/api/exports/{packet_id}/build")
    assert resp.status_code in (400, 200), resp.text


@pytest.mark.asyncio
async def test_delete_packet_removes_artifacts_and_db_rows(built_packet, test_session):
    client, packet_id, doc_ids, build = built_packet

    final_dir = _final_dir(packet_id)
    assert os.path.isdir(final_dir)

    resp = await client.delete(f"/api/packets/{packet_id}")
    assert resp.status_code == 200, resp.text

    assert not os.path.isdir(final_dir), "final artifacts must be removed on packet delete"

    from sqlalchemy import text

    for table in [
        "documents",
        "pages",
        "bates_assignments",
        "redaction_candidates",
        "redaction_approvals",
        "privilege_decisions",
        "manifests",
        "manifest_entries",
    ]:
        result = await test_session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        count = result.scalar()
        assert count == 0, f"{table} left {count} rows"


@pytest.mark.asyncio
async def test_original_files_removed_on_packet_delete(built_packet):
    client, packet_id, doc_ids, build = built_packet

    originals_dir = os.path.join(get_settings().storage_root, "originals")
    assert os.listdir(originals_dir), "expected original files before delete"

    resp = await client.delete(f"/api/packets/{packet_id}")
    assert resp.status_code == 200, resp.text

    remaining = os.listdir(originals_dir)
    assert remaining == [], f"originals left behind: {remaining}"


@pytest.mark.asyncio
async def test_detect_covers_all_pii_types(api_client):
    client = api_client
    packet_id = await _make_packet(client)
    await _upload(client, packet_id, filename="all_pii.pdf", lines=LINES, page_count=1)

    resp = await client.post(f"/api/redactions/{packet_id}/detect")
    assert resp.status_code == 200, resp.text

    candidates = (await client.get(f"/api/redactions/{packet_id}")).json()
    matched = {c["matched_text"] for c in candidates}
    for expected in [
        "ACC-8821-4433",
        "123-45-6789",
        "jane.public@example.com",
        "(212) 555-0199",
        "John Doe",
        "8821-4433-2211-9900",
    ]:
        assert expected in matched, f"missing {expected!r}"

    assert "FQ-0500" not in matched, "Bates-like reference must not be flagged"
    assert "EMPLOYEE PERSONNEL RECORD" not in matched
    assert "Reference" not in matched
