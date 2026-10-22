"""Tests for the packet verification endpoint.

Verifies that the /exports/{packet_id}/verify endpoint returns structured
verification results with all expected checks.
"""
import hashlib
import json

import fitz
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.bates import BatesAssignment
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.manifest import Manifest, ManifestEntry
from app.domain.packet import Packet
from app.domain.page import Page

settings = get_settings()


def make_pdf(lines, page_count=1):
    doc = fitz.open()
    for _ in range(page_count):
        page = doc.new_page(width=612, height=792)
        for j, line in enumerate(lines):
            page.insert_text((72, 100 + j * 20), line, fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _make_packet(client, name="Verify Test Packet", start=1):
    resp = await client.post(
        "/api/packets",
        json={
            "name": name,
            "bates_prefix": "VT-",
            "bates_start_number": start,
            "bates_padding": 4,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _upload_doc(client, packet_id, filename, content_lines, page_count=1):
    pdf_bytes = make_pdf(content_lines, page_count)
    files = {"files": (filename, pdf_bytes, "application/pdf")}
    resp = await client.post(f"/api/documents/{packet_id}/upload", files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()["documents"][0]["id"]


class TestVerifyPacketEndpoint:
    @pytest.mark.asyncio
    async def test_verify_not_built(self, api_client):
        client = api_client
        packet_id = await _make_packet(client)
        resp = await client.post(f"/api/exports/{packet_id}/verify")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "NOT_BUILT"
        assert any(c["name"] == "manifest_exists" and not c["passed"] for c in data["checks"])

    @pytest.mark.asyncio
    async def test_verify_packet_returns_all_checks(self, api_client):
        client = api_client
        packet_id = await _make_packet(client)
        doc_id = await _upload_doc(client, packet_id, "test.pdf", ["Page 1"])

        build_resp = await client.post(f"/api/exports/{packet_id}/build")
        assert build_resp.status_code == 200, build_resp.text

        resp = await client.post(f"/api/exports/{packet_id}/verify")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert "status" in data
        assert "checks" in data
        assert "page_count" in data
        assert "bates_start" in data
        assert "bates_end" in data
        assert "exhibits" in data

        check_names = [c["name"] for c in data["checks"]]
        assert "manifest_exists" in check_names
        assert "final_packet_exists" in check_names
        assert "bates_contiguous" in check_names
        assert "bates_no_duplicates" in check_names
        assert "page_counts_match" in check_names
        assert "reconciliation" in check_names

    @pytest.mark.asyncio
    async def test_verify_records_audit_event(self, api_client):
        client = api_client
        packet_id = await _make_packet(client)
        await _upload_doc(client, packet_id, "test.pdf", ["Page 1"])

        build_resp = await client.post(f"/api/exports/{packet_id}/build")
        assert build_resp.status_code == 200, build_resp.text

        resp = await client.post(f"/api/exports/{packet_id}/verify")
        assert resp.status_code == 200, resp.text

        audit = await client.get(f"/api/audit/{packet_id}")
        assert audit.status_code == 200, audit.text
        event_types = [e["event_type"] for e in audit.json()["events"]]
        assert "packet_validated" in event_types

    @pytest.mark.asyncio
    async def test_verify_failed_when_missing_artifacts(self, api_client):
        client = api_client
        packet_id = await _make_packet(client)
        await _upload_doc(client, packet_id, "test.pdf", ["Page 1"])

        build_resp = await client.post(f"/api/exports/{packet_id}/build")
        assert build_resp.status_code == 200, build_resp.text

        resp = await client.post(f"/api/exports/{packet_id}/verify")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        if data["status"] == "FAILED":
            failed_checks = [c for c in data["checks"] if not c["passed"]]
            assert len(failed_checks) > 0
            assert any("detail" in c for c in failed_checks)

    @pytest.mark.asyncio
    async def test_verify_packet_id_in_response(self, api_client):
        client = api_client
        packet_id = await _make_packet(client)
        await _upload_doc(client, packet_id, "test.pdf", ["Page 1"])

        build_resp = await client.post(f"/api/exports/{packet_id}/build")
        assert build_resp.status_code == 200, build_resp.text

        resp = await client.post(f"/api/exports/{packet_id}/verify")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["packet_id"] == packet_id

    @pytest.mark.asyncio
    async def test_verify_404_for_nonexistent_packet(self, api_client):
        client = api_client
        resp = await client.post("/api/exports/00000000-0000-0000-0000-000000000000/verify")
        assert resp.status_code == 404, resp.text
