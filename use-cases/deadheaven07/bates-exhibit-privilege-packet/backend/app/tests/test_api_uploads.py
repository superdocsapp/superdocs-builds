"""API-level tests for document upload, storage integrity and validation
(M-4 orphan-file prevention, L-3 packet validation, reference-aware cleanup).
"""

import os

import pytest

from app.config import get_settings
from qa_helpers import make_pdf, sha256_of


async def _make_packet(client, name="Upload QA Packet", start=1):
    resp = await client.post("/api/packets", json={
        "name": name, "bates_prefix": "UP-", "bates_start_number": start, "bates_padding": 4,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _originals_dir():
    return os.path.join(get_settings().storage_root, "originals")


def _orphan_pdfs():
    if not os.path.isdir(_originals_dir()):
        return []
    return [f for f in os.listdir(_originals_dir()) if f.endswith(".pdf")]


@pytest.mark.asyncio
async def test_upload_valid_pdf(api_client):
    client = api_client
    packet_id = await _make_packet(client)

    body = make_pdf(["Page one", "Page two"], page_count=2)
    files = {"files": ("evidence.pdf", body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert len(payload["documents"]) == 1
    doc = payload["documents"][0]
    assert doc["filename"] == "evidence.pdf"
    assert doc["status"] == "completed"
    assert doc["page_count"] == 2

    audit = await client.get(f"/api/audit/{packet_id}")
    types = [e["event_type"] for e in audit.json()["events"]]
    for expected in ["upload", "processing_started", "processing_completed", "bates_assigned"]:
        assert expected in types, f"missing {expected} in {types}"

    bates = await client.get(f"/api/bates/{packet_id}")
    assert bates.status_code == 200, bates.text
    assert bates.json()["total_assignments"] == 2
    labels = [a["bates_label"] for a in bates.json()["assignments"]]
    assert labels == ["UP-0001", "UP-0002"]


@pytest.mark.asyncio
async def test_upload_duplicate_content_409(api_client):
    client = api_client
    packet_id = await _make_packet(client)

    body = make_pdf(["Duplicated content"])
    files = {"files": ("dup_a.pdf", body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text

    files = {"files": ("dup_b.pdf", body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 409, resp.text

    docs = await client.get(f"/api/documents/{packet_id}")
    assert len(docs.json()) == 1


@pytest.mark.asyncio
async def test_corrupt_pdf_400_no_orphan_file(api_client):
    client = api_client
    packet_id = await _make_packet(client)

    files = {"files": ("broken.pdf", b"%PDF-1.4\nthis is not a real pdf\n%%EOF", "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 400, resp.text
    assert "Corrupt" in resp.json()["detail"]

    assert _orphan_pdfs() == [], f"orphan files left behind: {_orphan_pdfs()}"

    docs = await client.get(f"/api/documents/{packet_id}")
    assert len(docs.json()) == 0

    audit = await client.get(f"/api/audit/{packet_id}")
    types = [e["event_type"] for e in audit.json()["events"]]
    assert "upload_failed" in types or "upload" not in types


@pytest.mark.asyncio
async def test_unsupported_extension_400(api_client):
    client = api_client
    packet_id = await _make_packet(client)

    files = {"files": ("notes.txt", b"hello world", "text/plain")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 400, resp.text
    assert _orphan_pdfs() == []


@pytest.mark.asyncio
async def test_empty_file_400(api_client):
    client = api_client
    packet_id = await _make_packet(client)

    files = {"files": ("empty.pdf", b"", "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 400, resp.text
    assert _orphan_pdfs() == []


@pytest.mark.asyncio
async def test_oversized_file_400(api_client):
    client = api_client
    packet_id = await _make_packet(client)

    huge = os.urandom(6 * 1024 * 1024)
    files = {"files": ("huge.pdf", huge, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 400, resp.text
    assert _orphan_pdfs() == []


@pytest.mark.asyncio
async def test_upload_invalid_uuid_422(api_client):
    client = api_client
    files = {"files": ("x.pdf", make_pdf(["x"]), "application/pdf")}
    resp = await client.post("/api/documents/not-a-uuid/upload", files=files)
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_missing_packet_404(api_client):
    client = api_client
    files = {"files": ("x.pdf", make_pdf(["x"]), "application/pdf")}
    resp = await client.post(
        f"/api/documents/{'00000000-0000-0000-0000-000000000001'}/upload", files=files)
    assert resp.status_code == 404, resp.text
    assert _orphan_pdfs() == []


@pytest.mark.asyncio
async def test_batch_upload_rollback_leaves_no_docs_and_no_files(api_client):
    client = api_client
    packet_id = await _make_packet(client)

    good = make_pdf(["Good file"])
    files = [
        ("files", ("good.pdf", good, "application/pdf")),
        ("files", ("broken.pdf", b"%PDF-1.4\nnot real\n%%EOF", "application/pdf")),
    ]
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 400, resp.text

    docs = await client.get(f"/api/documents/{packet_id}")
    assert len(docs.json()) == 0, "partial batch left documents behind"

    assert _orphan_pdfs() == [], f"partial batch left orphan files: {_orphan_pdfs()}"


@pytest.mark.asyncio
async def test_negative_bates_start_rejected_422(api_client):
    client = api_client
    resp = await client.post("/api/packets", json={
        "name": "Bad Packet", "bates_prefix": "NG-",
        "bates_start_number": -5, "bates_padding": 4,
    })
    assert resp.status_code == 422, resp.text

    packet_id = await _make_packet(client)
    resp = await client.patch(f"/api/packets/{packet_id}", json={"bates_start_number": -1})
    assert resp.status_code == 422, resp.text

    resp = await client.post("/api/packets", json={
        "name": "Zero Padding", "bates_prefix": "ZP-",
        "bates_start_number": 1, "bates_padding": 0,
    })
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_delete_document_removes_referenced_files(api_client, tmp_path):
    client = api_client
    packet_id = await _make_packet(client)
    other_packet = await _make_packet(client, name="Other Packet", start=100)

    body = make_pdf(["Shared content"])
    files = {"files": ("shared.pdf", body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    doc_id = resp.json()["documents"][0]["id"]
    source_path = os.path.join(_originals_dir(), sha256_of(body) + ".pdf")
    assert os.path.exists(source_path)

    files = {"files": ("shared_copy.pdf", body, "application/pdf")}
    resp = await client.post(f"/api/documents/{other_packet}/upload", files=files)
    assert resp.status_code == 200, resp.text

    resp = await client.delete(f"/api/documents/{packet_id}/{doc_id}")
    assert resp.status_code == 200, resp.text
    assert os.path.exists(source_path), "shared file must be kept while another document references it"

    other_doc = (await client.get(f"/api/documents/{other_packet}")).json()[0]
    resp = await client.delete(f"/api/documents/{other_packet}/{other_doc['id']}")
    assert resp.status_code == 200, resp.text
    assert not os.path.exists(source_path), "file must be removed when no documents reference it"


@pytest.mark.asyncio
async def test_upload_then_retry_same_file_ok_after_delete(api_client):
    client = api_client
    packet_id = await _make_packet(client)

    body = make_pdf(["Retry me"])
    files = {"files": ("retry.pdf", body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    doc_id = resp.json()["documents"][0]["id"]

    await client.delete(f"/api/documents/{packet_id}/{doc_id}")

    files = {"files": ("retry_again.pdf", body, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text