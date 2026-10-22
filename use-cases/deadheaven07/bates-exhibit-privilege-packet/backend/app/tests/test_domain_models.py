import pytest
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.packet import Packet
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.page import Page
from app.domain.bates import BatesAssignment
from app.domain.privilege import PrivilegeDecision, PrivilegeStatus, PrivilegeCategory
from app.domain.redaction import RedactionCandidate, RedactionStatus, RedactionCategory, RedactionApproval
from app.domain.audit import AuditEvent, AuditEventType
from app.domain.manifest import Manifest, ManifestEntry


class TestPacketModel:
    @pytest.mark.asyncio
    async def test_create_packet(self, test_session: AsyncSession):
        packet = Packet(
            name="Test Packet",
            description="Test description",
            bates_prefix="CASE-",
            bates_start_number=1,
            bates_padding=6,
        )
        test_session.add(packet)
        await test_session.commit()
        await test_session.refresh(packet)

        assert packet.id is not None
        assert packet.name == "Test Packet"
        assert packet.bates_prefix == "CASE-"
        assert packet.bates_start_number == 1
        assert packet.bates_padding == 6
        assert packet.created_at is not None
        assert packet.updated_at is not None

    @pytest.mark.asyncio
    async def test_packet_next_display_order(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()
        await test_session.refresh(packet)

        # Query documents directly instead of relying on relationship lazy loading
        from sqlalchemy import select
        result = await test_session.execute(
            select(Document).where(Document.packet_id == packet.id)
        )
        docs = result.scalars().all()
        assert len(docs) == 0
        
        # Test that next_display_order logic works with session
        assert await packet.next_display_order(test_session) == 1


class TestDocumentModel:
    @pytest.mark.asyncio
    async def test_create_document(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="a" * 64,
            document_type=DocumentType.PDF,
            page_count=5,
            processing_status=ProcessingStatus.QUEUED,
            original_sha256="a" * 64,
        )
        test_session.add(document)
        await test_session.commit()
        await test_session.refresh(document)

        assert document.id is not None
        assert document.packet_id == packet.id
        assert document.display_order == 1
        assert document.original_filename == "test.pdf"
        assert document.document_type == DocumentType.PDF
        assert document.processing_status == ProcessingStatus.QUEUED
        assert document.is_searchable is False

    @pytest.mark.asyncio
    async def test_document_processing_status_enum(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        for status in ProcessingStatus:
            document = Document(
                packet_id=packet.id,
                display_order=1,
                original_filename=f"test_{status.value}.pdf",
                mime_type="application/pdf",
                file_size=1024,
                sha256="b" * 64,
                document_type=DocumentType.PDF,
                page_count=1,
                processing_status=status,
                original_sha256="b" * 64,
            )
            test_session.add(document)
            await test_session.commit()
            await test_session.refresh(document)
            assert document.processing_status == status


class TestPageModel:
    @pytest.mark.asyncio
    async def test_create_page(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="c" * 64,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.QUEUED,
            original_sha256="c" * 64,
        )
        test_session.add(document)
        await test_session.commit()

        page = Page(
            document_id=document.id,
            page_number=1,
            width=612.0,
            height=792.0,
            rotation=0,
            has_text=True,
            extracted_text="Sample text content",
        )
        test_session.add(page)
        await test_session.commit()
        await test_session.refresh(page)

        assert page.id is not None
        assert page.document_id == document.id
        assert page.page_number == 1
        assert page.has_text is True


class TestBatesAssignmentModel:
    @pytest.mark.asyncio
    async def test_create_bates_assignment(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet", bates_prefix="CASE-", bates_start_number=1, bates_padding=6)
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="d" * 64,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.QUEUED,
            original_sha256="d" * 64,
        )
        test_session.add(document)
        await test_session.commit()

        page = Page(
            document_id=document.id,
            page_number=1,
        )
        test_session.add(page)
        await test_session.commit()

        bates = BatesAssignment(
            packet_id=packet.id,
            document_id=document.id,
            page_id=page.id,
            page_number=1,
            bates_number=1,
            bates_label="CASE-000001",
        )
        test_session.add(bates)
        await test_session.commit()
        await test_session.refresh(bates)

        assert bates.id is not None
        assert bates.bates_number == 1
        assert bates.bates_label == "CASE-000001"
        assert bates.formatted_bates == "CASE-000001"

    @pytest.mark.asyncio
    async def test_bates_uniqueness_constraint(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="e" * 64,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.QUEUED,
            original_sha256="e" * 64,
        )
        test_session.add(document)
        await test_session.commit()

        page1 = Page(document_id=document.id, page_number=1)
        page2 = Page(document_id=document.id, page_number=2)
        test_session.add_all([page1, page2])
        await test_session.commit()

        bates1 = BatesAssignment(
            packet_id=packet.id,
            document_id=document.id,
            page_id=page1.id,
            page_number=1,
            bates_number=1,
            bates_label="CASE-000001",
        )
        bates2 = BatesAssignment(
            packet_id=packet.id,
            document_id=document.id,
            page_id=page2.id,
            page_number=2,
            bates_number=1,
            bates_label="CASE-000001",
        )
        test_session.add(bates1)
        await test_session.commit()

        test_session.add(bates2)
        with pytest.raises(Exception):
            await test_session.commit()


class TestPrivilegeDecisionModel:
    @pytest.mark.asyncio
    async def test_create_privilege_decision(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="f" * 64,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.QUEUED,
            original_sha256="f" * 64,
        )
        test_session.add(document)
        await test_session.commit()

        decision = PrivilegeDecision(
            packet_id=packet.id,
            document_id=document.id,
            status=PrivilegeStatus.PRIVILEGED,
            category=PrivilegeCategory.ATTORNEY_CLIENT,
            reason="Attorney-client communication",
            bates_start="CASE-000001",
            bates_end="CASE-000010",
            reviewer="john.doe@firm.com",
            decided_at=datetime.utcnow(),
        )
        test_session.add(decision)
        await test_session.commit()
        await test_session.refresh(decision)

        assert decision.id is not None
        assert decision.status == PrivilegeStatus.PRIVILEGED
        assert decision.category == PrivilegeCategory.ATTORNEY_CLIENT
        assert decision.reason == "Attorney-client communication"


class TestRedactionCandidateModel:
    @pytest.mark.asyncio
    async def test_create_redaction_candidate(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="g" * 64,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.QUEUED,
            original_sha256="g" * 64,
        )
        test_session.add(document)
        await test_session.commit()

        candidate = RedactionCandidate(
            document_id=document.id,
            page_number=1,
            category=RedactionCategory.NAME,
            matched_text="John Doe",
            context_before="Dear ",
            context_after=",",
            x0=100.0,
            y0=200.0,
            x1=200.0,
            y1=220.0,
            status=RedactionStatus.PROPOSED,
            proposed_by="system",
        )
        test_session.add(candidate)
        await test_session.commit()
        await test_session.refresh(candidate)

        assert candidate.id is not None
        assert candidate.category == RedactionCategory.NAME
        assert candidate.matched_text == "John Doe"
        assert candidate.status == RedactionStatus.PROPOSED


class TestRedactionApprovalModel:
    @pytest.mark.asyncio
    async def test_create_redaction_approval(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="h" * 64,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.QUEUED,
            original_sha256="h" * 64,
        )
        test_session.add(document)
        await test_session.commit()

        candidate = RedactionCandidate(
            document_id=document.id,
            page_number=1,
            category=RedactionCategory.NAME,
            matched_text="John Doe",
            status=RedactionStatus.PENDING_APPROVAL,
        )
        test_session.add(candidate)
        await test_session.commit()

        approval = RedactionApproval(
            candidate_id=candidate.id,
            status=RedactionStatus.APPROVED,
            approver="jane.doe@firm.com",
        )
        test_session.add(approval)
        await test_session.commit()
        await test_session.refresh(approval)

        assert approval.id is not None
        assert approval.candidate_id == candidate.id
        assert approval.status == RedactionStatus.APPROVED
        assert approval.approver == "jane.doe@firm.com"


class TestAuditEventModel:
    @pytest.mark.asyncio
    async def test_create_audit_event(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="i" * 64,
            document_type=DocumentType.PDF,
            page_count=1,
            processing_status=ProcessingStatus.QUEUED,
            original_sha256="i" * 64,
        )
        test_session.add(document)
        await test_session.commit()

        event = AuditEvent(
            packet_id=packet.id,
            document_id=document.id,
            event_type=AuditEventType.UPLOAD,
            user_id="user123",
            event_metadata={"filename": "test.pdf", "size": 1024},
        )
        test_session.add(event)
        await test_session.commit()
        await test_session.refresh(event)

        assert event.id is not None
        assert event.event_type == AuditEventType.UPLOAD
        assert event.user_id == "user123"
        assert event.event_metadata["filename"] == "test.pdf"


class TestManifestModel:
    @pytest.mark.asyncio
    async def test_create_manifest(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        manifest = Manifest(
            packet_id=packet.id,
            total_pages=100,
            total_documents=5,
            bates_start="CASE-000001",
            bates_end="CASE-000100",
            validation_passed=True,
            final_packet_sha256="j" * 64,
            final_packet_path="/final/packet.pdf",
        )
        test_session.add(manifest)
        await test_session.commit()
        await test_session.refresh(manifest)

        assert manifest.id is not None
        assert manifest.packet_id == packet.id
        assert manifest.total_pages == 100
        assert manifest.validation_passed is True

    @pytest.mark.asyncio
    async def test_create_manifest_entry(self, test_session: AsyncSession):
        packet = Packet(name="Test Packet")
        test_session.add(packet)
        await test_session.commit()

        document = Document(
            packet_id=packet.id,
            display_order=1,
            original_filename="test.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256="k" * 64,
            document_type=DocumentType.PDF,
            page_count=10,
            processing_status=ProcessingStatus.COMPLETED,
            original_sha256="k" * 64,
            processed_sha256="k" * 64,
            final_sha256="k" * 64,
        )
        test_session.add(document)
        await test_session.commit()

        manifest = Manifest(packet_id=packet.id, total_pages=10, total_documents=1)
        test_session.add(manifest)
        await test_session.commit()

        entry = ManifestEntry(
            manifest_id=manifest.id,
            document_id=document.id,
            exhibit_identifier="EX-A",
            bates_start="CASE-000001",
            bates_end="CASE-000010",
            page_count=10,
            original_sha256="k" * 64,
            processed_sha256="k" * 64,
            final_sha256="k" * 64,
            description="Employment agreement",
            privilege_status="not_privileged",
            applied_redactions=[],
            final_file_path="/final/EX-A.pdf",
        )
        test_session.add(entry)
        await test_session.commit()
        await test_session.refresh(entry)

        assert entry.id is not None
        assert entry.exhibit_identifier == "EX-A"
        assert entry.page_count == 10