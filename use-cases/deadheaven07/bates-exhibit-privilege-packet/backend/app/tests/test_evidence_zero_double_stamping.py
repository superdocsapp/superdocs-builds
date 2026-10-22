"""EVIDENCE: Zero double-stamping under idempotent re-assignment.

Claim: assign_bates() can be called any number of times on the same packet.
  - No page ever receives more than one Bates number.
  - Every (document_id, page_number) pair appears exactly once in the DB.
  - The bates_number sequence is always contiguous with no gaps.

Verification: a stranger can run `pytest test_evidence_zero_double_stamping.py`
  and see every assertion pass. Each test is self-contained: setup -> action -> invariant check.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.domain.page import Page
from app.services.bates_assignment import BatesAssignmentService


def _uuid(val):
    return str(val)


async def _create_packet(session, prefix="CASE-", start=1, padding=6):
    packet = Packet(
        name="Double-Stamp Evidence",
        bates_prefix=prefix,
        bates_start_number=start,
        bates_padding=padding,
    )
    session.add(packet)
    await session.commit()
    await session.refresh(packet)
    return packet


async def _create_documents(session, packet, page_counts):
    docs = []
    for i, pc in enumerate(page_counts):
        doc = Document(
            packet_id=packet.id,
            display_order=i + 1,
            original_filename=f"doc_{i}.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256=f"{'d' * 63}{i}",
            original_sha256=f"{'d' * 63}{i}",
            document_type=DocumentType.PDF,
            page_count=pc,
            processing_status=ProcessingStatus.COMPLETED,
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        for p in range(1, pc + 1):
            session.add(Page(document_id=doc.id, page_number=p))
        await session.commit()
        docs.append(doc)
    return docs


class TestZeroDoubleStamping:
    """Core invariant: no (document_id, page_number) ever appears twice."""

    @pytest.mark.asyncio
    async def test_assign_twice_no_duplicates(self, test_session: AsyncSession):
        """Assign bates, assign again, prove zero duplicate rows."""
        packet = await _create_packet(test_session)
        docs = await _create_documents(test_session, packet, [2, 3, 4])
        service = BatesAssignmentService()

        await service.assign_bates(test_session, packet.id)
        await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text(
                "SELECT document_id, page_number, COUNT(*) as cnt "
                "FROM bates_assignments WHERE packet_id = :pid "
                "GROUP BY document_id, page_number HAVING COUNT(*) > 1"
            ),
            {"pid": _uuid(packet.id)},
        )
        duplicates = result.fetchall()
        assert duplicates == [], f"Duplicate (doc, page) pairs found: {duplicates}"

    @pytest.mark.asyncio
    async def test_assign_thrice_no_duplicates(self, test_session: AsyncSession):
        """Assign bates three times. Zero duplicates every time."""
        packet = await _create_packet(test_session)
        docs = await _create_documents(test_session, packet, [3, 2])
        service = BatesAssignmentService()

        for _ in range(3):
            await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text(
                "SELECT document_id, page_number, COUNT(*) as cnt "
                "FROM bates_assignments WHERE packet_id = :pid "
                "GROUP BY document_id, page_number HAVING COUNT(*) > 1"
            ),
            {"pid": _uuid(packet.id)},
        )
        assert result.fetchall() == []

    @pytest.mark.asyncio
    async def test_total_rows_equals_total_pages(self, test_session: AsyncSession):
        """After N assigns, the number of rows equals the total page count exactly."""
        packet = await _create_packet(test_session)
        page_counts = [5, 3, 7, 2]
        docs = await _create_documents(test_session, packet, page_counts)
        total_pages = sum(page_counts)
        service = BatesAssignmentService()

        for _ in range(5):
            await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text("SELECT COUNT(*) FROM bates_assignments WHERE packet_id = :pid"),
            {"pid": _uuid(packet.id)},
        )
        count = result.scalar()
        assert count == total_pages, f"Expected {total_pages} rows, got {count}"

    @pytest.mark.asyncio
    async def test_bates_numbers_are_contiguous(self, test_session: AsyncSession):
        """After multiple assigns, bates_number is a contiguous range."""
        packet = await _create_packet(test_session, start=100)
        docs = await _create_documents(test_session, packet, [4, 6])
        service = BatesAssignmentService()

        for _ in range(3):
            await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text(
                "SELECT bates_number FROM bates_assignments "
                "WHERE packet_id = :pid ORDER BY bates_number"
            ),
            {"pid": _uuid(packet.id)},
        )
        numbers = [row.bates_number for row in result.fetchall()]
        assert numbers == list(range(100, 110)), f"Non-contiguous: {numbers}"

    @pytest.mark.asyncio
    async def test_no_bates_number_collisions(self, test_session: AsyncSession):
        """Every bates_number value is unique across the packet."""
        packet = await _create_packet(test_session)
        docs = await _create_documents(test_session, packet, [10, 10, 10])
        service = BatesAssignmentService()

        for _ in range(3):
            await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text(
                "SELECT bates_number, COUNT(*) as cnt "
                "FROM bates_assignments WHERE packet_id = :pid "
                "GROUP BY bates_number HAVING COUNT(*) > 1"
            ),
            {"pid": _uuid(packet.id)},
        )
        collisions = result.fetchall()
        assert collisions == [], f"Bates number collisions: {collisions}"

    @pytest.mark.asyncio
    async def test_labels_match_numbers(self, test_session: AsyncSession):
        """Every bates_label is the correctly formatted version of its bates_number."""
        packet = await _create_packet(test_session, prefix="EXH-", start=1, padding=4)
        docs = await _create_documents(test_session, packet, [3, 3])
        service = BatesAssignmentService()

        await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text(
                "SELECT bates_number, bates_label FROM bates_assignments "
                "WHERE packet_id = :pid ORDER BY bates_number"
            ),
            {"pid": _uuid(packet.id)},
        )
        for row in result.fetchall():
            expected_label = f"EXH-{str(row.bates_number).zfill(4)}"
            assert row.bates_label == expected_label, (
                f"Label mismatch: number={row.bates_number}, "
                f"expected={expected_label}, got={row.bates_label}"
            )

    @pytest.mark.asyncio
    async def test_large_packet_no_duplicates(self, test_session: AsyncSession):
        """Stress test: 50 pages across 5 documents. 10 assigns. Zero duplicates."""
        packet = await _create_packet(test_session)
        docs = await _create_documents(test_session, packet, [10, 10, 10, 10, 10])
        service = BatesAssignmentService()

        for _ in range(10):
            await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text(
                "SELECT COUNT(*) FROM bates_assignments WHERE packet_id = :pid"
            ),
            {"pid": _uuid(packet.id)},
        )
        assert result.scalar() == 50

        result = await test_session.execute(
            text(
                "SELECT document_id, page_number, COUNT(*) "
                "FROM bates_assignments WHERE packet_id = :pid "
                "GROUP BY document_id, page_number HAVING COUNT(*) > 1"
            ),
            {"pid": _uuid(packet.id)},
        )
        assert result.fetchall() == []
