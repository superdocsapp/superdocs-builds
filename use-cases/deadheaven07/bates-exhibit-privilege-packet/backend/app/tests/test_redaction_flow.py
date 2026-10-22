import hashlib

import fitz
import pytest
from qa_helpers import FakeSuperDocsService
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.domain.redaction import (
    RedactionApproval,
    RedactionStatus,
)
from app.services.redaction import (
    RedactionApplicationService,
    RedactionDetectionService,
    db_candidates_to_superdocs,
)

settings = get_settings()


def make_pdf(lines):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for j, line in enumerate(lines):
        page.insert_text((72, 100 + j * 20), line, fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestRedactionFlow:
    @pytest.fixture
    async def document_with_pii(self, test_session: AsyncSession):
        packet = Packet(name="Redaction Test Packet")
        test_session.add(packet)
        await test_session.commit()
        await test_session.refresh(packet)

        pdf_bytes = make_pdf(
            [
                "Employee: Jane Q Public",
                "SSN: 123-45-6789",
                "Email: jane.public@example.com",
            ]
        )
        sha = sha256_of(pdf_bytes)
        original_path = settings.originals_path / f"{sha}.pdf"
        original_path.parent.mkdir(parents=True, exist_ok=True)
        original_path.write_bytes(pdf_bytes)

        doc = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="pii_employee.pdf",
            mime_type="application/pdf",
            file_size=len(pdf_bytes),
            sha256=sha,
            original_sha256=sha,
            processed_sha256=sha,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.COMPLETED,
            description="PII test document",
        )
        test_session.add(doc)
        await test_session.commit()
        await test_session.refresh(doc)

        yield packet, doc, original_path

        for suffix in [".pdf", "_redacted.pdf"]:
            f = settings.originals_path / f"{doc.sha256}{suffix}"
            if f.exists():
                f.unlink()
            f = settings.working_path / f"{doc.sha256}{suffix}"
            if f.exists():
                f.unlink()

    @pytest.mark.asyncio
    async def test_detect_finds_pii_candidates(self, test_session: AsyncSession, document_with_pii):
        packet, doc, original_path = document_with_pii
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)

        pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))
        assert pii_result.total_count >= 2
        assert any(e.text == "123-45-6789" for e in pii_result.entities)

        candidates = await detection.create_redaction_candidates(
            test_session, str(doc.id), pii_result
        )
        for c in candidates:
            test_session.add(c)
        await test_session.commit()
        assert len(candidates) >= 2
        assert all(c.status == RedactionStatus.PROPOSED for c in candidates), (
            f"unexpected statuses: {[c.status for c in candidates]}"
        )

    @pytest.mark.asyncio
    async def test_repeated_detect_is_idempotent(
        self, test_session: AsyncSession, document_with_pii
    ):
        packet, doc, original_path = document_with_pii
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)

        first = await detection.detect_pii_in_document(test_session, str(doc.id))
        created, skipped = await detection.reconcile_candidates(
            test_session,
            str(doc.id),
            (await detection.create_redaction_candidates(test_session, str(doc.id), first)),
        )
        for c in created:
            test_session.add(c)
        await test_session.commit()
        assert skipped == 0
        assert len(created) >= 2

        second = await detection.detect_pii_in_document(test_session, str(doc.id))
        created_again, skipped_again = await detection.reconcile_candidates(
            test_session,
            str(doc.id),
            (await detection.create_redaction_candidates(test_session, str(doc.id), second)),
        )
        assert created_again == []
        assert skipped_again == len(created), "re-detect must not duplicate candidates"

    @pytest.mark.asyncio
    async def test_approve_apply_verify_flow(self, test_session: AsyncSession, document_with_pii):
        packet, doc, original_path = document_with_pii
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)
        application = RedactionApplicationService(superdocs=fake)

        pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))
        candidates = await detection.create_redaction_candidates(
            test_session, str(doc.id), pii_result
        )
        ssn_candidate = next(c for c in candidates if c.matched_text == "123-45-6789")
        email_candidate = next(c for c in candidates if "jane.public" in c.matched_text)

        test_session.add_all(candidates)
        await test_session.flush()

        ssn_candidate.status = RedactionStatus.APPROVED
        approval = RedactionApproval(
            candidate_id=ssn_candidate.id,
            status=RedactionStatus.APPROVED,
            approver="reviewer-1",
        )
        test_session.add(approval)
        await test_session.commit()

        results = await application.apply_redactions(
            test_session, doc, [ssn_candidate, email_candidate]
        )

        assert results[str(ssn_candidate.id)]["applied"] is True
        assert str(email_candidate.id) not in results, "unapproved candidate must be skipped"

        redacted_path = settings.working_path / f"{doc.sha256}_redacted.pdf"
        assert redacted_path.exists()

        verification = await application.verify_redactions(
            test_session, doc, [ssn_candidate, email_candidate]
        )
        assert verification[str(ssn_candidate.id)]["verified"] is True
        assert verification[str(email_candidate.id)]["verified"] is False, (
            "unapproved candidate must not be verified"
        )

        redacted_doc = fitz.open(redacted_path)
        try:
            redacted_text = redacted_doc[0].get_text()
        finally:
            redacted_doc.close()
        assert "123-45-6789" not in redacted_text
        assert "jane.public@example.com" in redacted_text

    @pytest.mark.asyncio
    async def test_rejected_candidate_is_skipped(
        self, test_session: AsyncSession, document_with_pii
    ):
        packet, doc, original_path = document_with_pii
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)
        application = RedactionApplicationService(superdocs=fake)

        pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))
        candidates = await detection.create_redaction_candidates(
            test_session, str(doc.id), pii_result
        )
        ssn_candidate = next(c for c in candidates if c.matched_text == "123-45-6789")

        test_session.add(ssn_candidate)
        await test_session.flush()

        ssn_candidate.status = RedactionStatus.REJECTED
        test_session.add(
            RedactionApproval(
                candidate_id=ssn_candidate.id,
                status=RedactionStatus.REJECTED,
                approver="reviewer-1",
            )
        )
        await test_session.commit()

        results = await application.apply_redactions(test_session, doc, [ssn_candidate])

        assert str(ssn_candidate.id) not in results, (
            "rejected candidates must be skipped by apply_redactions"
        )

    @pytest.mark.asyncio
    async def test_db_candidates_convert_to_superdocs(
        self, test_session: AsyncSession, document_with_pii
    ):
        packet, doc, original_path = document_with_pii
        fake = FakeSuperDocsService()
        detection = RedactionDetectionService(superdocs=fake)

        pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))
        candidates = await detection.create_redaction_candidates(
            test_session, str(doc.id), pii_result
        )
        approved = list(candidates)
        for c in approved:
            c.status = RedactionStatus.APPROVED

        converted = db_candidates_to_superdocs(approved)
        assert len(converted) == len(approved)
        assert all(c.approved for c in converted)
        assert all(c.entity.text for c in converted)
