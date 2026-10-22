import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.domain.page import Page
from app.services.bates_assignment import BatesAssignmentService


def uuid_to_str(uuid_val):
    """Convert UUID to string for SQLite compatibility."""
    return str(uuid_val)


class TestBatesAssignmentService:
    @pytest.fixture
    def service(self):
        return BatesAssignmentService()

    @pytest.fixture
    async def sample_packet(self, test_session: AsyncSession):
        packet = Packet(
            name="Test Packet",
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
        for i in range(3):
            doc = Document(
                packet_id=sample_packet.id,
                display_order=i + 1,
                original_filename=f"doc_{i + 1}.pdf",
                mime_type="application/pdf",
                file_size=1024,
                sha256=f"{'a' * 63}{i}",
                document_type=DocumentType.PDF,
                page_count=(i + 1) * 2,
                processing_status=ProcessingStatus.COMPLETED,
                original_sha256=f"{'a' * 63}{i}",
            )
            test_session.add(doc)
            await test_session.commit()
            await test_session.refresh(doc)

            for page_num in range(1, doc.page_count + 1):
                page = Page(document_id=doc.id, page_number=page_num)
                test_session.add(page)
            docs.append(doc)

        await test_session.commit()
        return docs

    @pytest.mark.asyncio
    async def test_assign_bates_deterministic(
        self,
        test_session: AsyncSession,
        service: BatesAssignmentService,
        sample_packet: Packet,
        sample_documents,
    ):
        await service.assign_bates(test_session, sample_packet.id)

        result = await test_session.execute(
            text("SELECT * FROM bates_assignments WHERE packet_id = :pid ORDER BY bates_number"),
            {"pid": uuid_to_str(sample_packet.id)},
        )
        rows = result.fetchall()

        assert len(rows) == 12

        expected_numbers = list(range(1, 13))
        actual_numbers = [row.bates_number for row in rows]
        assert actual_numbers == expected_numbers

        expected_labels = [f"CASE-{str(n).zfill(6)}" for n in expected_numbers]
        actual_labels = [row.bates_label for row in rows]
        assert actual_labels == expected_labels

    @pytest.mark.asyncio
    async def test_assign_bates_respects_display_order(
        self,
        test_session: AsyncSession,
        service: BatesAssignmentService,
        sample_packet: Packet,
        sample_documents,
    ):
        await service.assign_bates(test_session, sample_packet.id)

        result = await test_session.execute(
            text(
                "SELECT document_id, page_number, bates_number FROM bates_assignments "
                "WHERE packet_id = :pid ORDER BY bates_number"
            ),
            {"pid": uuid_to_str(sample_packet.id)},
        )
        rows = result.fetchall()

        doc_1_pages = [r for r in rows if r.document_id == sample_documents[0].id]
        doc_2_pages = [r for r in rows if r.document_id == sample_documents[1].id]
        doc_3_pages = [r for r in rows if r.document_id == sample_documents[2].id]

        assert len(doc_1_pages) == 2
        assert len(doc_2_pages) == 4
        assert len(doc_3_pages) == 6

        assert doc_1_pages[0].bates_number == 1
        assert doc_1_pages[1].bates_number == 2
        assert doc_2_pages[0].bates_number == 3
        assert doc_3_pages[-1].bates_number == 12

    @pytest.mark.asyncio
    async def test_assign_bates_custom_start_number(
        self, test_session: AsyncSession, sample_packet: Packet, sample_documents
    ):
        sample_packet.bates_start_number = 100
        await test_session.commit()

        service = BatesAssignmentService()
        await service.assign_bates(test_session, sample_packet.id)

        result = await test_session.execute(
            text(
                "SELECT bates_number FROM bates_assignments "
                "WHERE packet_id = :pid ORDER BY bates_number"
            ),
            {"pid": uuid_to_str(sample_packet.id)},
        )
        rows = result.fetchall()

        expected = list(range(100, 112))
        actual = [row.bates_number for row in rows]
        assert actual == expected

    @pytest.mark.asyncio
    async def test_assign_bates_custom_padding(
        self, test_session: AsyncSession, sample_packet: Packet, sample_documents
    ):
        sample_packet.bates_padding = 4
        await test_session.commit()

        service = BatesAssignmentService()
        await service.assign_bates(test_session, sample_packet.id)

        result = await test_session.execute(
            text(
                "SELECT bates_label FROM bates_assignments "
                "WHERE packet_id = :pid ORDER BY bates_number"
            ),
            {"pid": uuid_to_str(sample_packet.id)},
        )
        rows = result.fetchall()

        expected_labels = [f"CASE-{str(n).zfill(4)}" for n in range(1, 13)]
        actual_labels = [row.bates_label for row in rows]
        assert actual_labels == expected_labels

    @pytest.mark.asyncio
    async def test_assign_bates_idempotent(
        self,
        test_session: AsyncSession,
        service: BatesAssignmentService,
        sample_packet: Packet,
        sample_documents,
    ):
        await service.assign_bates(test_session, sample_packet.id)

        result = await test_session.execute(
            text("SELECT COUNT(*) FROM bates_assignments WHERE packet_id = :pid"),
            {"pid": uuid_to_str(sample_packet.id)},
        )
        first_count = result.scalar()

        await service.assign_bates(test_session, sample_packet.id)

        result = await test_session.execute(
            text("SELECT COUNT(*) FROM bates_assignments WHERE packet_id = :pid"),
            {"pid": uuid_to_str(sample_packet.id)},
        )
        second_count = result.scalar()
        assert first_count == 12
        assert second_count == 12

    @pytest.mark.asyncio
    async def test_assign_bates_skip_incomplete_documents(
        self,
        test_session: AsyncSession,
        service: BatesAssignmentService,
        sample_packet: Packet,
        sample_documents,
    ):
        sample_documents[1].processing_status = ProcessingStatus.PROCESSING
        await test_session.commit()

        await service.assign_bates(test_session, sample_packet.id)

        result = await test_session.execute(
            text(
                "SELECT document_id, COUNT(*) FROM bates_assignments "
                "WHERE packet_id = :pid GROUP BY document_id"
            ),
            {"pid": uuid_to_str(sample_packet.id)},
        )
        rows = result.fetchall()

        doc_ids_with_bates = {row.document_id for row in rows}
        assert sample_documents[0].id in doc_ids_with_bates
        assert sample_documents[1].id not in doc_ids_with_bates
        assert sample_documents[2].id in doc_ids_with_bates


class TestBatesNumberFormatting:
    def test_format_bates_number(self):
        from app.services.bates_assignment import format_bates_number

        assert format_bates_number("CASE-", 1, 6) == "CASE-000001"
        assert format_bates_number("CASE-", 100, 6) == "CASE-000100"
        assert format_bates_number("EXH-", 1, 4) == "EXH-0001"
        assert format_bates_number("", 1, 6) == "000001"
        assert format_bates_number("A-", 999999, 6) == "A-999999"

    def test_parse_bates_number(self):
        from app.services.bates_assignment import parse_bates_number

        prefix, number = parse_bates_number("CASE-000001", "CASE-")
        assert prefix == "CASE-"
        assert number == 1

        prefix, number = parse_bates_number("EXH-0001", "EXH-")
        assert prefix == "EXH-"
        assert number == 1

        with pytest.raises(ValueError):
            parse_bates_number("INVALID", "CASE-")
