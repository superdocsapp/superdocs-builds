import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.bates import BatesAssignment
from app.domain.document import Document, ProcessingStatus
from app.domain.packet import Packet
from app.domain.page import Page
from app.services.bates_journal import BatesJournal, JournalEntry
from app.time import utc_now

settings = get_settings()


def format_bates_number(prefix: str, number: int, padding: int) -> str:
    return f"{prefix}{str(number).zfill(padding)}"


def parse_bates_number(bates_label: str, prefix: str) -> tuple[str, int]:
    if not bates_label.startswith(prefix):
        raise ValueError(f"Bates label {bates_label} does not match prefix {prefix}")
    number_str = bates_label[len(prefix) :]
    try:
        return prefix, int(number_str)
    except ValueError:
        raise ValueError(f"Invalid Bates number format: {bates_label}") from None


class BatesAssignmentService:
    async def assign_bates(
        self,
        session: AsyncSession,
        packet_id: str | uuid.UUID,
    ) -> list[BatesAssignment]:
        """Assign Bates numbers to all completed documents in display order.

        Idempotent / crash-resume: existing assignments for the packet are
        never destructively wiped when pages are simply re-assigned. Already-
        assigned pages are skipped and numbering resumes at
        ``MAX(bates_number) + 1``. A crash mid-run thus never loses prior
        state, never double-stamps, and the final sequence can be proven
        gap-free via ``BatesJournal.prove_continuity``.

        When the document configuration has changed (i.e. the maximum bates
        number in existing assignments exceeds what the current completed
        documents would expect starting from ``bates_start_number``), all
        existing assignments are cleared and the remaining documents are
        renumbered from ``bates_start_number`` to produce a contiguous
        sequence with no gaps and no double-stamping.
        """
        packet = await session.get(Packet, packet_id)
        if not packet:
            raise ValueError(f"Packet {packet_id} not found")

        journal = BatesJournal(settings.working_path / f"bates_journal_{packet_id}.jsonl")

        # Step 1: Load existing database assignments (never delete up front)
        existing = await session.execute(
            select(BatesAssignment).where(BatesAssignment.packet_id == packet_id)
        )
        db_assignments: list[BatesAssignment] = existing.scalars().all()

        # Step 2: Build the set of (document_id, page_number) already assigned
        already_assigned: set[tuple[int, int]] = {
            (a.document_id, a.page_number) for a in db_assignments
        }

        # Step 3: Check if document configuration has changed.
        # If the max bates_number in existing assignments exceeds what the
        # current completed documents would expect (bates_start_number +
        # current_total_pages - 1), clear all assignments and renumber
        # from bates_start_number. This handles document removal and new
        # document addition scenarios.
        current_documents_result = await session.execute(
            select(Document).where(Document.packet_id == packet_id)
            .where(Document.processing_status == ProcessingStatus.COMPLETED)
            .order_by(Document.display_order)
        )
        current_documents: Sequence[Document] = current_documents_result.scalars().all()
        current_total_pages = sum(d.page_count for d in current_documents)

        # Check if existing assignments match contiguous sequence across display order
        order_valid = True
        if db_assignments:
            expected_current_num = packet.bates_start_number
            seen_unassigned = False
            for doc in current_documents:
                doc_assignments = sorted(
                    [a for a in db_assignments if a.document_id == doc.id],
                    key=lambda a: a.page_number,
                )
                if not doc_assignments:
                    seen_unassigned = True
                    continue
                if seen_unassigned:
                    # An assigned document appears after an unassigned document
                    order_valid = False
                    break
                for a in doc_assignments:
                    if a.bates_number != expected_current_num:
                        order_valid = False
                        break
                    expected_current_num += 1
                if not order_valid:
                    break

        if db_assignments:
            db_max = max(a.bates_number for a in db_assignments)
            expected_max = packet.bates_start_number + current_total_pages - 1
            if db_max > expected_max or not order_valid:
                # Configuration or display order changed: clear all and renumber from start
                for assignment in db_assignments:
                    await session.delete(assignment)
                await session.flush()
                next_number = packet.bates_start_number
                already_assigned = set()
            else:
                # Step 4: Resume number from the journal / DB max
                next_number = journal.resume_start(packet.bates_start_number)
                if db_assignments:
                    db_max = max(a.bates_number for a in db_assignments)
                    next_number = max(next_number, db_max + 1)
        else:
            # No existing assignments: start from bates_start_number
            next_number = packet.bates_start_number
            already_assigned = set()

        # Step 5: Load completed documents in display order
        documents_result = await session.execute(
            select(Document).where(Document.packet_id == packet_id)
            .where(Document.processing_status == ProcessingStatus.COMPLETED)
            .order_by(Document.display_order)
        )
        documents: Sequence[Document] = documents_result.scalars().all()

        assignments: list[BatesAssignment] = []

        for document in documents:
            pages_result = await session.execute(
                select(Page).where(Page.document_id == document.id).order_by(Page.page_number)
            )
            pages: Sequence[Page] = pages_result.scalars().all()

            for page in pages:
                # Skip pages already assigned (crash-resume); in
                # config-change mode, already_assigned is empty so all
                # pages are reassigned from start.
                if (document.id, page.page_number) in already_assigned:
                    continue

                bates_label = format_bates_number(
                    packet.bates_prefix, next_number, packet.bates_padding
                )
                assignment = BatesAssignment(
                    packet_id=packet_id,
                    document_id=document.id,
                    page_id=page.id,
                    page_number=page.page_number,
                    bates_number=next_number,
                    bates_label=bates_label,
                )
                session.add(assignment)
                assignments.append(assignment)
                journal.append(
                    JournalEntry(
                        page_key=f"{document.id}:p{page.page_number}",
                        document_id=str(document.id),
                        page_number=page.page_number,
                        bates_number=next_number,
                        bates_label=bates_label,
                        assigned_at=utc_now().isoformat(),
                    )
                )
                next_number += 1

        await session.commit()
        return assignments

    async def get_bates_assignments(
        self,
        session: AsyncSession,
        packet_id: str | uuid.UUID,
    ) -> list[BatesAssignment]:
        result = await session.execute(
            select(BatesAssignment)
            .where(BatesAssignment.packet_id == packet_id)
            .order_by(BatesAssignment.bates_number)
        )
        return list(result.scalars().all())

    async def preview_bates(
        self,
        session: AsyncSession,
        packet_id: str | uuid.UUID,
    ) -> list[dict]:
        packet = await session.get(Packet, packet_id)
        if not packet:
            raise ValueError(f"Packet {packet_id} not found")

        documents_result = await session.execute(
            select(Document).where(Document.packet_id == packet_id).order_by(Document.display_order)
        )
        documents: Sequence[Document] = documents_result.scalars().all()

        preview = []
        current_number = packet.bates_start_number

        for document in documents:
            if document.processing_status != ProcessingStatus.COMPLETED:
                preview.append(
                    {
                        "document_id": str(document.id),
                        "document_name": document.original_filename,
                        "page_count": document.page_count,
                        "status": document.processing_status.value,
                        "bates_start": None,
                        "bates_end": None,
                        "skipped": True,
                    }
                )
                continue

            bates_start = format_bates_number(
                packet.bates_prefix, current_number, packet.bates_padding
            )
            current_number += document.page_count
            bates_end = format_bates_number(
                packet.bates_prefix, current_number - 1, packet.bates_padding
            )

            preview.append(
                {
                    "document_id": str(document.id),
                    "document_name": document.original_filename,
                    "page_count": document.page_count,
                    "status": document.processing_status.value,
                    "bates_start": bates_start,
                    "bates_end": bates_end,
                    "skipped": False,
                }
            )

        return preview
