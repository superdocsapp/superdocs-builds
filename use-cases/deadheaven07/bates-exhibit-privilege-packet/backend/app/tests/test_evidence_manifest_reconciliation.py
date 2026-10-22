"""EVIDENCE: Manifest SHA-256 reconciliation.

Claim: After building a packet, every SHA-256 hash in manifest.json matches
  the actual file on disk. A stranger can independently verify by:
  1. Running this test.
  2. Re-hashing any file referenced in the manifest.
  3. Comparing with the recorded hash.

Verification: `pytest test_evidence_manifest_reconciliation.py`
  Requires: PostgreSQL test DB, no SuperDocs API key.
"""

import hashlib
import json

import fitz
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.domain.page import Page
from app.services.bates_assignment import BatesAssignmentService
from app.services.packet_builder import PacketBuilderService

settings = get_settings()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_original(pdf_bytes, sha):
    path = settings.originals_path / f"{sha}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes)
    return path


def _make_pdf(lines):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for j, line in enumerate(lines):
        page.insert_text((72, 100 + j * 20), line, fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


async def _setup_and_build(session, doc_specs):
    """Create packet, documents, pages, originals, assign bates, build.

    doc_specs: list of dicts with 'lines' (text for PDF) and 'sha' (hash).
    Returns (packet, build_result, final_dir).
    """
    packet = Packet(
        name="Manifest Evidence",
        bates_prefix="CASE-",
        bates_start_number=1,
        bates_padding=6,
    )
    session.add(packet)
    await session.commit()
    await session.refresh(packet)

    for i, spec in enumerate(doc_specs):
        pdf_bytes = _make_pdf(spec["lines"])
        _write_original(pdf_bytes, spec["sha"])

        doc = Document(
            packet_id=packet.id,
            display_order=i + 1,
            original_filename=f"doc_{i}.pdf",
            mime_type="application/pdf",
            file_size=len(pdf_bytes),
            sha256=spec["sha"],
            original_sha256=spec["sha"],
            processed_sha256=spec["sha"],
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.COMPLETED,
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

        session.add(Page(document_id=doc.id, page_number=1))
        await session.commit()

    bates_service = BatesAssignmentService()
    await bates_service.assign_bates(session, packet.id)

    builder = PacketBuilderService()
    result = await builder.build_packet(session, str(packet.id))

    return packet, result


class TestManifestReconciliationEvidence:
    """Prove every SHA-256 in manifest.json matches the actual file on disk."""

    @pytest.mark.asyncio
    async def test_final_packet_sha_matches(self, test_session: AsyncSession):
        """The final_packet.sha256 in manifest matches the actual file hash."""
        docs = [
            {"lines": ["Document A content"], "sha": "a" * 64},
            {"lines": ["Document B content"], "sha": "b" * 64},
        ]
        packet, result = await _setup_and_build(test_session, docs)

        manifest_path = result.manifest_path
        assert manifest_path.exists()
        manifest_data = json.loads(manifest_path.read_text())

        declared_sha = manifest_data["final_packet"]["sha256"]
        actual_sha = _sha256(result.final_packet_path)

        assert declared_sha == actual_sha, (
            f"final_packet SHA mismatch: manifest={declared_sha}, actual={actual_sha}"
        )

    @pytest.mark.asyncio
    async def test_each_exhibit_sha_matches(self, test_session: AsyncSession):
        """Every exhibit entry's final_sha256 matches the actual EX-*.pdf on disk."""
        docs = [
            {"lines": ["Exhibit A"], "sha": "a" * 64},
            {"lines": ["Exhibit B"], "sha": "b" * 64},
            {"lines": ["Exhibit C"], "sha": "c" * 64},
        ]
        packet, result = await _setup_and_build(test_session, docs)

        manifest_data = json.loads(result.manifest_path.read_text())

        for entry in manifest_data["entries"]:
            exhibit_id = entry["exhibit_identifier"]
            declared_sha = entry["final_sha256"]
            exhibit_path = result.exhibits_dir / f"{exhibit_id}.pdf"

            assert exhibit_path.exists(), f"{exhibit_id}.pdf missing"
            actual_sha = _sha256(exhibit_path)
            assert declared_sha == actual_sha, (
                f"{exhibit_id} SHA mismatch: manifest={declared_sha}, actual={actual_sha}"
            )

    @pytest.mark.asyncio
    async def test_all_entries_have_sha(self, test_session: AsyncSession):
        """Every entry in manifest.json has a non-empty final_sha256."""
        docs = [
            {"lines": ["Doc 1"], "sha": "a" * 64},
            {"lines": ["Doc 2"], "sha": "b" * 64},
        ]
        packet, result = await _setup_and_build(test_session, docs)

        manifest_data = json.loads(result.manifest_path.read_text())
        assert len(manifest_data["entries"]) == 2

        for entry in manifest_data["entries"]:
            assert entry["final_sha256"], f"Missing SHA for {entry['exhibit_identifier']}"
            assert len(entry["final_sha256"]) == 64, f"Invalid SHA length for {entry['exhibit_identifier']}"

    @pytest.mark.asyncio
    async def test_manifest_bates_range_matches_assignments(self, test_session: AsyncSession):
        """Manifest bates_start/bates_end match the actual DB assignments."""
        docs = [
            {"lines": ["Doc 1 page 1"], "sha": "a" * 64},
            {"lines": ["Doc 2 page 1"], "sha": "b" * 64},
        ]
        packet, result = await _setup_and_build(test_session, docs)

        manifest_data = json.loads(result.manifest_path.read_text())

        assert manifest_data["bates_start"] == "CASE-000001"
        assert manifest_data["bates_end"] == "CASE-000002"
        assert manifest_data["total_documents"] == 2
        # Each document gets a cover sheet (+1 page), so 2 docs x (1 content + 1 cover) = 4
        assert manifest_data["total_pages"] == 4

    @pytest.mark.asyncio
    async def test_manifest_page_count_matches_files(self, test_session: AsyncSession):
        """Sum of entry page_counts equals the total_pages in the manifest.
        Each document gets a cover sheet, so page_count = doc.page_count + 1."""
        docs = [
            {"lines": ["Page 1"], "sha": "a" * 64},
            {"lines": ["Page 2"], "sha": "b" * 64},
            {"lines": ["Page 3"], "sha": "c" * 64},
        ]
        packet, result = await _setup_and_build(test_session, docs)

        manifest_data = json.loads(result.manifest_path.read_text())
        entry_pages = sum(e["page_count"] for e in manifest_data["entries"])
        assert entry_pages == manifest_data["total_pages"]
        # 3 docs x (1 content + 1 cover) = 6
        assert manifest_data["total_pages"] == 6

    @pytest.mark.asyncio
    async def test_redacted_text_masked_in_manifest(self, test_session: AsyncSession):
        """applied_redactions in manifest have matched_text='***', not raw PII."""
        from app.domain.redaction import (
            RedactionApproval,
            RedactionCandidate,
            RedactionCategory,
            RedactionStatus,
        )
        from app.time import utc_now

        sha = "f" * 64
        pdf_bytes = _make_pdf(["SSN: 123-45-6789"])
        _write_original(pdf_bytes, sha)

        packet = Packet(
            name="Mask Evidence",
            bates_prefix="CASE-",
            bates_start_number=1,
            bates_padding=6,
        )
        test_session.add(packet)
        await test_session.commit()
        await test_session.refresh(packet)

        doc = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="mask_test.pdf",
            mime_type="application/pdf",
            file_size=len(pdf_bytes),
            sha256=sha,
            original_sha256=sha,
            processed_sha256=sha,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.COMPLETED,
        )
        test_session.add(doc)
        await test_session.commit()
        await test_session.refresh(doc)

        test_session.add(Page(document_id=doc.id, page_number=1))
        await test_session.commit()

        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="123-45-6789",
            context_before="",
            context_after="",
            x0=72, y0=88, x1=200, y1=102,
            status=RedactionStatus.APPROVED,
        )
        test_session.add(candidate)
        await test_session.commit()
        await test_session.refresh(candidate)

        approval = RedactionApproval(
            candidate_id=candidate.id,
            status=RedactionStatus.APPROVED,
            approver="test-user",
            approved_at=utc_now(),
        )
        test_session.add(approval)
        await test_session.commit()

        from app.services.redaction import RedactionApplicationService
        app_service = RedactionApplicationService()
        await app_service.apply_redactions(test_session, doc, [candidate])

        await test_session.refresh(candidate)
        candidate.status = RedactionStatus.APPLIED
        await test_session.commit()

        bates_service = BatesAssignmentService()
        await bates_service.assign_bates(test_session, packet.id)

        builder = PacketBuilderService()
        result = await builder.build_packet(test_session, str(packet.id))

        manifest_data = json.loads(result.manifest_path.read_text())
        for entry in manifest_data["entries"]:
            for redaction in entry.get("applied_redactions", []):
                assert redaction["matched_text"] == "***", (
                    f"Raw PII exposed in manifest: {redaction['matched_text']}"
                )

    @pytest.mark.asyncio
    async def test_manifest_json_is_valid_json(self, test_session: AsyncSession):
        """manifest.json parses without error and has required top-level keys."""
        docs = [
            {"lines": ["Content"], "sha": "a" * 64},
        ]
        packet, result = await _setup_and_build(test_session, docs)

        raw = result.manifest_path.read_text()
        data = json.loads(raw)

        required_keys = [
            "packet_id", "packet_name", "generated_at",
            "total_pages", "total_documents",
            "bates_start", "bates_end",
            "final_packet", "entries",
        ]
        for key in required_keys:
            assert key in data, f"Missing key: {key}"

        assert len(data["entries"]) == 1
        assert data["entries"][0]["exhibit_identifier"] == "EX-A"
