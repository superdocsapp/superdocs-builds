import hashlib
import json
from datetime import UTC, datetime

import fitz
import pytest
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.packet import Packet
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.page import Page
from app.domain.bates import BatesAssignment
from app.domain.manifest import Manifest, ManifestEntry
from app.domain.redaction import RedactionCandidate, RedactionApproval, RedactionStatus, RedactionCategory
from app.services.packet_builder import PacketBuilderService

settings = get_settings()


def make_pdf(lines, page_count=1):
    """Render a real PDF (with extractable text) using PyMuPDF."""
    doc = fitz.open()
    for i in range(page_count):
        page = doc.new_page(width=612, height=792)
        for j, line in enumerate(lines):
            page.insert_text((72, 100 + j * 20), line, fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestPacketBuilderService:
    @pytest.fixture
    def builder(self):
        return PacketBuilderService()

    @pytest.fixture
    async def sample_packet(self, test_session: AsyncSession):
        packet = Packet(
            name="Builder Test Packet",
            bates_prefix="CASE-",
            bates_start_number=1,
            bates_padding=6,
        )
        test_session.add(packet)
        await test_session.commit()
        await test_session.refresh(packet)
        return packet

    @pytest.fixture
    async def sample_documents(self, test_session: AsyncSession, sample_packet: Packet):
        docs = []
        for i, (filename, pages, content) in enumerate([
            ("exhibit_a.pdf", 2, ["Exhibit A content one", "Exhibit A content two"]),
            ("exhibit_b.pdf", 1, ["Exhibit B content"]),
        ]):
            pdf_bytes = make_pdf(content, pages)
            sha = sha256_of(pdf_bytes)
            original_path = settings.originals_path / f"{sha}.pdf"
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(pdf_bytes)

            doc = Document(
                packet_id=sample_packet.id,
                display_order=i + 1,
                original_filename=filename,
                mime_type="application/pdf",
                file_size=len(pdf_bytes),
                sha256=sha,
                original_sha256=sha,
                processed_sha256=sha,
                document_type=DocumentType.PDF,
                page_count=pages,
                processing_status=ProcessingStatus.COMPLETED,
                description=f"Description of {filename}",
            )
            test_session.add(doc)
            await test_session.commit()
            await test_session.refresh(doc)

            for page_num in range(1, pages + 1):
                page = Page(document_id=doc.id, page_number=page_num)
                test_session.add(page)
            docs.append(doc)

        await test_session.commit()
        return docs

    @pytest.fixture
    async def bates_assigned(self, test_session: AsyncSession, sample_packet: Packet, sample_documents):
        number = sample_packet.bates_start_number
        for doc in sample_documents:
            pages_result = await test_session.execute(
                text("SELECT * FROM pages WHERE document_id = :did ORDER BY page_number"),
                {"did": str(doc.id)},
            )
            for page in pages_result.fetchall():
                assignment = BatesAssignment(
                    packet_id=sample_packet.id,
                    document_id=page.document_id,
                    page_id=page.id,
                    page_number=page.page_number,
                    bates_number=number,
                    bates_label=f"{sample_packet.bates_prefix}{str(number).zfill(sample_packet.bates_padding)}",
                )
                test_session.add(assignment)
                number += 1
        await test_session.commit()
        return sample_packet, sample_documents

    async def _cleanup(self, packet_id: str, docs):
        final_dir = settings.final_path / str(packet_id)
        if final_dir.exists():
            for f in final_dir.rglob("*"):
                if f.is_file():
                    f.unlink()
            try:
                final_dir.rmdir()
            except OSError:
                pass
        for doc in docs:
            for suffix in [".pdf", "_stamped.pdf", "_redacted.pdf", "_searchable.pdf"]:
                f = settings.working_path / f"{doc.sha256}{suffix}"
                if f.exists():
                    f.unlink()
            f = settings.originals_path / f"{doc.sha256}.pdf"
            if f.exists():
                f.unlink()

    @pytest.mark.asyncio
    async def test_build_packet_creates_final_packet_and_manifest(
        self, test_session: AsyncSession, builder: PacketBuilderService, bates_assigned
    ):
        packet, docs = bates_assigned
        total_source_pages = sum(d.page_count for d in docs)
        result = await builder.build_packet(test_session, packet.id)

        assert result.final_packet_path.exists()
        assert result.exhibit_index_path.exists()
        assert result.privilege_log_path.exists()
        assert result.manifest_path.exists()
        assert result.manifest.validation_passed is True
        assert result.manifest.total_documents == 2
        assert result.manifest.total_pages == total_source_pages + 2

        final_reader = PdfReader(str(result.final_packet_path))
        assert len(final_reader.pages) == total_source_pages + 2

        final_doc = fitz.open(result.final_packet_path)
        try:
            cover_text = final_doc[0].get_text()
            assert "EXHIBIT A" in cover_text
            assert "Bates Range" in cover_text
            assert "CASE-000001 - CASE-000002" in cover_text
            assert "Description of exhibit_a.pdf" in cover_text

            stamped_text = final_doc[1].get_text()
            assert "CASE-000001" in stamped_text
            assert "Exhibit A content one" in stamped_text

            last_stamped_text = final_doc[-1].get_text()
            assert "CASE-000003" in last_stamped_text
        finally:
            final_doc.close()

        index_doc = fitz.open(result.exhibit_index_path)
        try:
            index_text = index_doc[0].get_text()
            assert "EXHIBIT INDEX" in index_text
            assert "A | CASE-000001 - CASE-000002" in index_text
            assert "B | CASE-000003 - CASE-000003" in index_text
        finally:
            index_doc.close()

        log_doc = fitz.open(result.privilege_log_path)
        try:
            assert "PRIVILEGE LOG" in log_doc[0].get_text()
        finally:
            log_doc.close()

        manifest_data = json.loads(result.manifest_path.read_text())
        assert manifest_data["packet_id"] == str(packet.id)
        assert manifest_data["total_pages"] == total_source_pages + 2
        assert manifest_data["validation_passed"] is True
        assert len(manifest_data["entries"]) == 2
        assert manifest_data["entries"][0]["exhibit_identifier"] == "EX-A"
        assert manifest_data["entries"][0]["page_count"] == 3

        db_result = await test_session.execute(
            select(Manifest).where(Manifest.packet_id == packet.id)
        )
        db_manifest = db_result.scalars().first()
        assert db_manifest is not None
        assert db_manifest.total_pages == total_source_pages + 2

        db_entries = await test_session.execute(
            select(ManifestEntry).where(ManifestEntry.manifest_id == db_manifest.id)
        )
        entries = db_entries.scalars().all()
        assert len(entries) == 2

        await self._cleanup(packet.id, docs)

    @pytest.mark.asyncio
    async def test_build_packet_records_applied_redactions_in_manifest(
        self, test_session: AsyncSession, builder: PacketBuilderService, bates_assigned
    ):
        packet, docs = bates_assigned
        doc = docs[0]

        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="CASE-000001",
            context_before="",
            context_after="",
            x0=0, y0=0, x1=0, y1=0,
            status=RedactionStatus.APPLIED,
        )
        test_session.add(candidate)
        await test_session.flush()
        test_session.add(RedactionApproval(
            candidate_id=candidate.id,
            status=RedactionStatus.APPLIED,
            approver="tester",
            applied_at=datetime.now(UTC),
            verified_at=datetime.now(UTC),
            verification_passed=True,
        ))
        await test_session.commit()

        result = await builder.build_packet(test_session, packet.id)
        manifest_data = json.loads(result.manifest_path.read_text())

        applied = [e for e in manifest_data["entries"] if e["exhibit_identifier"] == "EX-A"][0]
        assert len(applied["applied_redactions"]) == 1
        assert applied["applied_redactions"][0]["candidate_id"] == str(candidate.id)
        assert applied["applied_redactions"][0]["verified"] is True

        await self._cleanup(packet.id, docs)

    @pytest.mark.asyncio
    async def test_validate_packet_reports_gaps(
        self, test_session: AsyncSession, builder: PacketBuilderService, bates_assigned
    ):
        packet, docs = bates_assigned

        result = await builder.validate_packet(test_session, packet.id)
        assert result["valid"] is True
        assert result["total_documents"] == 2
        assert result["total_pages"] == 5

        missing = await test_session.execute(
            text("DELETE FROM bates_assignments WHERE packet_id = :pid AND bates_number = 2"),
            {"pid": str(packet.id)},
        )
        await test_session.commit()

        result = await builder.validate_packet(test_session, packet.id)
        assert result["valid"] is False
        assert any("gaps" in e for e in result["errors"])

        await self._cleanup(packet.id, docs)