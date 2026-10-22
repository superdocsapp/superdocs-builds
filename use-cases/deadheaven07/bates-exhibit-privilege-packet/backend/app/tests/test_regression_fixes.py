import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import fitz
import pytest
from qa_helpers import FakeSuperDocsService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.bates import BatesAssignment
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.manifest import Manifest
from app.domain.packet import Packet
from app.domain.page import Page
from app.domain.redaction import (
    RedactionApproval,
    RedactionCandidate,
    RedactionCategory,
    RedactionStatus,
)
from app.services.bates_assignment import BatesAssignmentService
from app.services.packet_builder import PacketBuilderService
from app.services.redaction import RedactionApplicationService, RedactionDetectionService
from app.services.storage import (
    base_pdf_source,
    cleanup_document_files,
    original_path_for,
    redacted_pdf_path_for,
)

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


def _write_original(pdf_bytes: bytes) -> str:
    sha = sha256_of(pdf_bytes)
    path = settings.originals_path / f"{sha}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf_bytes)
    return sha


def _cleanup(sha: str):
    for root in [settings.originals_path, settings.working_path, settings.processed_path]:
        for f in root.glob(f"{sha}*"):
            f.unlink(missing_ok=True)


async def _make_document(
    session: AsyncSession,
    packet: Packet,
    pdf_bytes: bytes,
    filename: str,
    display_order=1,
    pages=None,
):
    sha = _write_original(pdf_bytes)
    with fitz.open(stream=pdf_bytes) as probe:
        count = pages or probe.page_count
    doc = Document(
        packet_id=packet.id,
        display_order=display_order,
        original_filename=filename,
        mime_type="application/pdf",
        file_size=len(pdf_bytes),
        sha256=sha,
        original_sha256=sha,
        processed_sha256=sha,
        document_type=DocumentType.PDF,
        page_count=count,
        processing_status=ProcessingStatus.COMPLETED,
        description=f"Description of {filename}",
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    for page_num in range(1, count + 1):
        session.add(Page(document_id=doc.id, page_number=page_num))
    await session.commit()
    return doc


async def _assign_bates(session: AsyncSession, packet: Packet, docs):
    number = packet.bates_start_number
    for doc in sorted(docs, key=lambda d: d.display_order):
        pages = (
            (
                await session.execute(
                    select(Page).where(Page.document_id == doc.id).order_by(Page.page_number)
                )
            )
            .scalars()
            .all()
        )
        for page in pages:
            session.add(
                BatesAssignment(
                    packet_id=packet.id,
                    document_id=doc.id,
                    page_id=page.id,
                    page_number=page.page_number,
                    bates_number=number,
                    bates_label=f"{packet.bates_prefix}{str(number).zfill(packet.bates_padding)}",
                )
            )
            number += 1
    await session.commit()


async def _seed_doc_with_bates(session: AsyncSession, pdf_bytes: bytes, filename: str):
    packet = Packet(
        name=f"Regression {filename}",
        bates_prefix="CASE-",
        bates_start_number=1,
        bates_padding=6,
    )
    session.add(packet)
    await session.commit()
    await session.refresh(packet)
    doc = await _make_document(session, packet, pdf_bytes, filename)
    await _assign_bates(session, packet, [doc])
    return packet, doc


class TestRegressionPerOccurrenceRedaction:
    @pytest.fixture
    async def doc_ssn(self, test_session: AsyncSession):
        pdf_bytes = make_pdf(
            [
                "First record SSN: 123-45-6789",
                "Second record SSN: 123-45-6789",
            ]
        )
        packet, doc = await _seed_doc_with_bates(test_session, pdf_bytes, "ssn_twice.pdf")
        yield packet, doc
        _cleanup(doc.sha256)
        if (settings.final_path / str(packet.id)).exists():
            import shutil

            shutil.rmtree(settings.final_path / str(packet.id))

    async def test_detection_returns_ssn_candidates(self, test_session: AsyncSession, doc_ssn):
        packet, doc = doc_ssn
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)

        pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))
        candidates = await detection.create_redaction_candidates(
            test_session, str(doc.id), pii_result
        )
        ssn_candidates = [c for c in candidates if c.category == RedactionCategory.SSN]

        assert len(ssn_candidates) >= 1
        assert {c.matched_text for c in ssn_candidates} == {"123-45-6789"}

    async def test_apply_redacts_every_occurrence(self, test_session: AsyncSession, doc_ssn):
        packet, doc = doc_ssn
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)
        application = RedactionApplicationService(superdocs=fake)

        pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))
        candidates = await detection.create_redaction_candidates(
            test_session, str(doc.id), pii_result
        )
        for c in candidates:
            c.status = RedactionStatus.APPROVED
        test_session.add_all(candidates)
        await test_session.commit()

        results = await application.apply_redactions(test_session, doc, candidates)
        assert all(r["applied"] for r in results.values())

        verification = await application.verify_redactions(test_session, doc, candidates)
        assert all(v["verified"] for v in verification.values())

        output = redacted_pdf_path_for(doc)
        pdf = fitz.open(output)
        try:
            text = pdf[0].get_text()
        finally:
            pdf.close()
        assert text.count("123-45-6789") == 0

    async def test_apply_is_idempotent_from_same_base(self, test_session: AsyncSession, doc_ssn):
        packet, doc = doc_ssn
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)
        application = RedactionApplicationService(superdocs=fake)

        pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))
        candidates = await detection.create_redaction_candidates(
            test_session, str(doc.id), pii_result
        )
        for c in candidates:
            c.status = RedactionStatus.APPROVED
        test_session.add_all(candidates)
        await test_session.commit()

        await application.apply_redactions(test_session, doc, candidates)
        output = redacted_pdf_path_for(doc)
        with fitz.open(output) as first_pdf:
            first_fills = len(first_pdf[0].get_drawings())
            first_text = first_pdf[0].get_text()

        await application.apply_redactions(test_session, doc, candidates)
        with fitz.open(output) as second_pdf:
            second_fills = len(second_pdf[0].get_drawings())
            second_text = second_pdf[0].get_text()

        assert "123-45-6789" not in first_text
        assert second_text == first_text, "re-applying must not compound redactions"
        assert second_fills == first_fills, "redaction regions must not duplicate on re-apply"


class TestRedactionCrossLineAndVerify:
    @pytest.fixture
    async def doc_split_name(self, test_session: AsyncSession):
        pdf_bytes = make_pdf(
            [
                "Patient name is",
                "John",
                "Doe",
                "Single line name: John Doe",
            ]
        )
        packet, doc = await _seed_doc_with_bates(test_session, pdf_bytes, "split_name.pdf")
        yield packet, doc
        _cleanup(doc.sha256)
        if (settings.final_path / str(packet.id)).exists():
            import shutil

            shutil.rmtree(settings.final_path / str(packet.id))

    async def test_name_split_across_lines_not_detected(
        self, test_session: AsyncSession, doc_split_name
    ):
        packet, doc = doc_split_name
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)

        pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))
        candidates = await detection.create_redaction_candidates(
            test_session, str(doc.id), pii_result
        )
        name_candidates = [c for c in candidates if c.category == RedactionCategory.NAME]

        assert any(c.matched_text == "John Doe" for c in name_candidates), (
            "single-line name must still be detected"
        )
        assert not any(
            c.matched_text == "John" or c.matched_text == "Doe" for c in name_candidates
        ), "line fragments must not be flagged as names"

    async def test_apply_only_removes_target_text(self, test_session: AsyncSession, doc_split_name):
        packet, doc = doc_split_name
        fake = FakeSuperDocsService()
        application = RedactionApplicationService(superdocs=fake)

        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.NAME,
            matched_text="John Doe",
            context_before="",
            context_after="",
            x0=0,
            y0=0,
            x1=0,
            y1=0,
            status=RedactionStatus.APPROVED,
        )
        results = await application.apply_redactions(test_session, doc, [candidate])
        assert results[str(candidate.id)]["applied"] is True

        output = redacted_pdf_path_for(doc)
        pdf = fitz.open(output)
        try:
            text = pdf[0].get_text()
        finally:
            pdf.close()
        assert "John Doe" not in text
        assert "Patient name is" in text, "unrelated content must be preserved"

    async def test_apply_completes_for_text_not_in_document(
        self, test_session: AsyncSession, doc_split_name
    ):
        packet, doc = doc_split_name
        fake = FakeSuperDocsService()
        application = RedactionApplicationService(superdocs=fake)

        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="123-45-6789",
            context_before="",
            context_after="",
            x0=0,
            y0=0,
            x1=0,
            y1=0,
            status=RedactionStatus.APPROVED,
        )
        results = await application.apply_redactions(test_session, doc, [candidate])
        assert results[str(candidate.id)]["applied"] is True
        assert redacted_pdf_path_for(doc).exists()


class TestBuildGateAndRebuild:
    async def _docs_with_redacted_file(
        self, test_session: AsyncSession, with_verification: bool, tamper: bool
    ):
        pdf_bytes = make_pdf(["Top secret SSN: 123-45-6789"])
        packet, doc = await _seed_doc_with_bates(test_session, pdf_bytes, "gate.pdf")

        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="123-45-6789",
            context_before="",
            context_after="",
            x0=0,
            y0=0,
            x1=0,
            y1=0,
            status=RedactionStatus.APPLIED,
        )
        test_session.add(candidate)
        await test_session.flush()
        test_session.add(
            RedactionApproval(
                candidate_id=candidate.id,
                status=RedactionStatus.APPLIED,
                approver="tester",
                applied_at=datetime.now(UTC),
                verified_at=datetime.now(UTC),
                verification_passed=with_verification,
            )
        )
        await test_session.commit()

        application = RedactionApplicationService(superdocs=FakeSuperDocsService())
        await application.apply_redactions(test_session, doc, [candidate])
        if tamper:
            output = redacted_pdf_path_for(doc)
            pdf = fitz.open(output)
            page = pdf[0]
            page.insert_text((72, 300), "123-45-6789", fontsize=12, fontname="helv")
            pdf.save(output, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            pdf.close()
        return packet, doc

    async def test_build_scrubs_redacted_terms_from_descriptions(self, test_session: AsyncSession):
        pdf_bytes = make_pdf(["EMPLOYEE RECORD", "SSN: 123-45-6789"])
        packet, doc = await _seed_doc_with_bates(test_session, pdf_bytes, "scrub.pdf")
        doc.description = "EMPLOYEE RECORD SSN: 123-45-6789 record for John Doe"
        doc.description_source = "content_summary"
        await test_session.commit()

        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="123-45-6789",
            context_before="",
            context_after="",
            x0=0,
            y0=0,
            x1=0,
            y1=0,
            status=RedactionStatus.APPLIED,
        )
        test_session.add(candidate)
        await test_session.flush()
        test_session.add(
            RedactionApproval(
                candidate_id=candidate.id,
                status=RedactionStatus.APPLIED,
                approver="tester",
                applied_at=datetime.now(UTC),
                verified_at=datetime.now(UTC),
                verification_passed=True,
            )
        )
        await test_session.commit()

        application = RedactionApplicationService(superdocs=FakeSuperDocsService())
        await application.apply_redactions(test_session, doc, [candidate])

        builder = PacketBuilderService()
        result = await builder.build_packet(test_session, packet.id)
        manifest_data = json.loads(result.manifest_path.read_text())
        assert "123-45-6789" not in manifest_data["entries"][0]["description"]
        assert "[REDACTED]" in manifest_data["entries"][0]["description"]

        final_doc = fitz.open(result.final_packet_path)
        try:
            cover_text = final_doc[0].get_text()
        finally:
            final_doc.close()
        assert "123-45-6789" not in cover_text
        assert "[REDACTED]" in cover_text

        import shutil

        shutil.rmtree(settings.final_path / str(packet.id))
        _cleanup(doc.sha256)

    async def test_build_refuses_applied_redaction_still_present(self, test_session: AsyncSession):
        packet, doc = await self._docs_with_redacted_file(
            test_session, with_verification=True, tamper=True
        )
        builder = PacketBuilderService()
        with pytest.raises(ValueError, match="still present in the redacted file"):
            await builder.build_packet(test_session, packet.id)
        _cleanup(doc.sha256)
        import shutil

        if (settings.final_path / str(packet.id)).exists():
            shutil.rmtree(settings.final_path / str(packet.id))

    async def test_build_refuses_unverified_applied_redaction_without_file(
        self, test_session: AsyncSession
    ):
        pdf_bytes = make_pdf(["Secret"])
        packet, doc = await _seed_doc_with_bates(test_session, pdf_bytes, "unverified.pdf")

        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="123-45-6789",
            context_before="",
            context_after="",
            x0=0,
            y0=0,
            x1=0,
            y1=0,
            status=RedactionStatus.APPLIED,
        )
        test_session.add(candidate)
        await test_session.flush()
        test_session.add(
            RedactionApproval(
                candidate_id=candidate.id,
                status=RedactionStatus.APPLIED,
                approver="tester",
                applied_at=datetime.now(UTC),
                verification_passed=False,
            )
        )
        await test_session.commit()

        builder = PacketBuilderService()
        with pytest.raises(ValueError, match="no verified redacted file"):
            await builder.build_packet(test_session, packet.id)
        _cleanup(doc.sha256)
        import shutil

        if (settings.final_path / str(packet.id)).exists():
            shutil.rmtree(settings.final_path / str(packet.id))

    async def test_rebuild_replaces_manifest_and_final_dir(self, test_session: AsyncSession):
        pdf_bytes = make_pdf(["Rebuild content"])
        packet, doc = await _seed_doc_with_bates(test_session, pdf_bytes, "rebuild.pdf")
        builder = PacketBuilderService()

        first = await builder.build_packet(test_session, packet.id)
        second = await builder.build_packet(test_session, packet.id)

        manifests = (
            (await test_session.execute(select(Manifest).where(Manifest.packet_id == packet.id)))
            .scalars()
            .all()
        )
        assert len(manifests) == 1, "rebuild must replace the manifest, not accumulate"

        final_dir = settings.final_path / str(packet.id)
        assert (final_dir / "manifest.json").exists()
        assert first.final_packet_path.read_bytes() == second.final_packet_path.read_bytes()

        assert (final_dir / "final_packet.pdf").exists()
        import hashlib

        actual = hashlib.sha256((final_dir / "final_packet.pdf").read_bytes()).hexdigest()
        assert manifests[0].final_packet_sha256 == actual

        import shutil

        shutil.rmtree(final_dir)
        _cleanup(doc.sha256)

    async def test_validate_detects_display_order_bates_mismatch(self, test_session: AsyncSession):
        pdf_a = make_pdf(["Doc A"])
        pdf_b = make_pdf(["Doc B"])
        packet = Packet(
            name="Order Test",
            bates_prefix="CASE-",
            bates_start_number=1,
            bates_padding=6,
        )
        test_session.add(packet)
        await test_session.commit()
        await test_session.refresh(packet)
        doc_a = await _make_document(test_session, packet, pdf_a, "a.pdf", display_order=1)
        doc_b = await _make_document(test_session, packet, pdf_b, "b.pdf", display_order=2)
        await _assign_bates(test_session, packet, [doc_a, doc_b])

        doc_a.display_order = 2
        doc_b.display_order = 1
        await test_session.commit()

        builder = PacketBuilderService()
        result = await builder.validate_packet(test_session, packet.id)
        assert result["valid"] is False
        assert any("contiguous across display order" in e for e in result["errors"])

        _cleanup(doc_a.sha256)
        _cleanup(doc_b.sha256)


class TestBatesFullReassign:
    async def test_assign_bates_renumbers_after_document_removal(self, test_session: AsyncSession):
        pdf_a = make_pdf(["Doc A content"], page_count=2)
        pdf_b = make_pdf(["Doc B content"])
        packet = Packet(
            name="Renumber Test",
            bates_prefix="CASE-",
            bates_start_number=1,
            bates_padding=6,
        )
        test_session.add(packet)
        await test_session.commit()
        await test_session.refresh(packet)
        doc_a = await _make_document(test_session, packet, pdf_a, "a.pdf", display_order=1)
        doc_b = await _make_document(test_session, packet, pdf_b, "b.pdf", display_order=2)
        await _assign_bates(test_session, packet, [doc_a, doc_b])

        for bates in (
            (
                await test_session.execute(
                    select(BatesAssignment).where(BatesAssignment.document_id == doc_a.id)
                )
            )
            .scalars()
            .all()
        ):
            await test_session.delete(bates)
        await test_session.delete(doc_a)
        await test_session.commit()

        service = BatesAssignmentService()
        assignments = await service.assign_bates(test_session, packet.id)
        assert len(assignments) == 1

        remaining = (
            (
                await test_session.execute(
                    select(BatesAssignment).where(BatesAssignment.packet_id == packet.id)
                )
            )
            .scalars()
            .all()
        )
        numbers = sorted(ba.bates_number for ba in remaining)
        assert numbers == [1], f"must restart contiguously at start number, got {numbers}"
        assert all(ba.bates_label == "CASE-000001" for ba in remaining)

        _cleanup(doc_a.sha256)
        _cleanup(doc_b.sha256)


class TestStorageCleanup:
    async def test_cleanup_is_reference_aware(self, test_session: AsyncSession):
        pdf_bytes = make_pdf(["Shared content"])
        sha = _write_original(pdf_bytes)

        packet_a = Packet(name="Packet A")
        test_session.add(packet_a)
        await test_session.commit()
        await test_session.refresh(packet_a)
        doc_a = await _make_document(test_session, packet_a, pdf_bytes, "shared.pdf")

        packet_b = Packet(name="Packet B")
        test_session.add(packet_b)
        await test_session.commit()
        await test_session.refresh(packet_b)
        doc_b = await _make_document(test_session, packet_b, pdf_bytes, "shared.pdf")

        assert original_path_for(doc_a).exists()

        removed = await cleanup_document_files(test_session, doc_a)
        assert removed == [], "files still referenced by packet B must be kept"
        assert original_path_for(doc_a).exists()

        await test_session.delete(doc_a)
        await test_session.commit()

        removed = await cleanup_document_files(test_session, doc_b)
        assert any(Path(p).name.startswith(sha) for p in removed), (
            "files must be removed on last reference"
        )
        assert not original_path_for(doc_b).exists(), "last reference must remove the file"

        _cleanup(sha)

    async def test_base_pdf_source_falls_back_to_processed(self, test_session: AsyncSession):
        pdf_bytes = make_pdf(["Converted content"])
        sha = _write_original(pdf_bytes)
        processed = settings.processed_path / f"{sha}.pdf"
        processed.parent.mkdir(parents=True, exist_ok=True)
        processed.write_bytes(pdf_bytes)

        packet = Packet(name="Fallback Test")
        test_session.add(packet)
        await test_session.commit()
        await test_session.refresh(packet)
        doc = await _make_document(test_session, packet, pdf_bytes, "converted.pdf")

        (settings.originals_path / f"{sha}.pdf").unlink()
        source = base_pdf_source(doc)
        assert source is not None
        assert source == processed

        _cleanup(sha)
