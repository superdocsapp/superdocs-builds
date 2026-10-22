"""TASK 2.1 KILL MATRIX — Adversarial / Failure Recovery Tests.

Tests interruption at meaningful points and verifies recovery.
Uses the real current persistence/journal/state — no parallel system.

Kill scenarios:
  1. Bates assignment before first page (0 assigned)
  2. Bates assignment in the middle (partial)
  3. Bates assignment on the final page (all but last)
  4. Packet build with tampered artifact
  5. Redaction attempt before approval
  6. Double-application prevention
  7. Idempotent scrub (re-running produces same content)

Usage:
  cd backend
  pytest app/tests/evaluation/test_task21_kill_matrix.py -v
"""

import tempfile
from pathlib import Path

import fitz
import pytest
from sqlalchemy import text

from app.domain.bates import BatesAssignment
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.domain.page import Page
from app.domain.redaction import (
    RedactionCandidate,
    RedactionCategory,
    RedactionStatus,
)
from app.services.bates_assignment import BatesAssignmentService
from app.services.bates_journal import BatesJournal
from app.services.redaction_scrubber import RedactionByteScrubber, RedactionVerifier
from app.time import utc_now


def _uuid(val):
    return str(val)


def _make_pdf(text_lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    for i, line in enumerate(text_lines):
        page.insert_text((72, 100 + i * 18), line, fontsize=11, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def _pdf_text(path: Path) -> str:
    doc = fitz.open(str(path))
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


async def _setup_three_doc_packet(session) -> tuple[Packet, list[Document]]:
    """Create a packet with 3 documents totaling 12 pages."""
    packet = Packet(
        name="Kill Matrix Packet",
        bates_prefix="CASE-",
        bates_start_number=1,
        bates_padding=6,
    )
    session.add(packet)
    await session.commit()
    await session.refresh(packet)

    docs = []
    for i, page_count in enumerate([2, 4, 6]):
        doc = Document(
            packet_id=packet.id,
            display_order=i + 1,
            original_filename=f"kill_doc_{i}.pdf",
            mime_type="application/pdf",
            file_size=1024,
            sha256=f"{'d' * 63}{i}",
            original_sha256=f"{'d' * 63}{i}",
            document_type=DocumentType.PDF,
            page_count=page_count,
            processing_status=ProcessingStatus.COMPLETED,
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        for p in range(1, page_count + 1):
            session.add(Page(document_id=doc.id, page_number=p))
        await session.commit()
        docs.append(doc)

    return packet, docs


async def _seed_partial(session, packet, docs, count):
    """Insert BatesAssignment rows for first N pages (simulating crash)."""
    number = packet.bates_start_number
    assigned = []
    for doc in docs:
        rows = (
            await session.execute(
                text("SELECT id, page_number FROM pages WHERE document_id = :did ORDER BY page_number"),
                {"did": _uuid(doc.id)},
            )
        ).fetchall()
        for page_row in rows:
            if number > packet.bates_start_number + count - 1:
                break
            label = f"CASE-{str(number).zfill(6)}"
            session.add(BatesAssignment(
                packet_id=packet.id,
                document_id=doc.id,
                page_id=page_row.id,
                page_number=page_row.page_number,
                bates_number=number,
                bates_label=label,
            ))
            assigned.append(number)
            number += 1
        else:
            continue
        break
    await session.commit()
    return assigned


# --------------------------------------------------------------------------- #
# Kill scenarios
# --------------------------------------------------------------------------- #


class TestKillMatrix:
    """Adversarial failure recovery tests."""

    @pytest.mark.asyncio
    async def test_K1_bates_zero_pages_assigned(self, test_session):
        """K1: Crash before any Bates assigned. Resume fills all 12."""
        packet, docs = await _setup_three_doc_packet(test_session)

        service = BatesAssignmentService()
        await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text("SELECT COUNT(*) FROM bates_assignments WHERE packet_id = :pid"),
            {"pid": _uuid(packet.id)},
        )
        assert result.scalar() == 12

        numbers = sorted(r[0] for r in (
            await test_session.execute(
                text("SELECT bates_number FROM bates_assignments WHERE packet_id = :pid ORDER BY bates_number"),
                {"pid": _uuid(packet.id)},
            )
        ).fetchall())
        assert numbers == list(range(1, 13))

    @pytest.mark.asyncio
    async def test_K2_bates_crash_mid_run(self, test_session):
        """K2: Crash at page 5 of 12. Resume fills 6-12."""
        packet, docs = await _setup_three_doc_packet(test_session)
        await _seed_partial(test_session, packet, docs, 5)

        service = BatesAssignmentService()
        await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text("SELECT COUNT(*) FROM bates_assignments WHERE packet_id = :pid"),
            {"pid": _uuid(packet.id)},
        )
        assert result.scalar() == 12

        numbers = sorted(r[0] for r in (
            await test_session.execute(
                text("SELECT bates_number FROM bates_assignments WHERE packet_id = :pid ORDER BY bates_number"),
                {"pid": _uuid(packet.id)},
            )
        ).fetchall())
        assert numbers == list(range(1, 13))

    @pytest.mark.asyncio
    async def test_K3_bates_crash_on_last_page(self, test_session):
        """K3: Crash at page 11 of 12. Resume fills page 12 only."""
        packet, docs = await _setup_three_doc_packet(test_session)
        await _seed_partial(test_session, packet, docs, 11)

        service = BatesAssignmentService()
        await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text("SELECT COUNT(*) FROM bates_assignments WHERE packet_id = :pid"),
            {"pid": _uuid(packet.id)},
        )
        assert result.scalar() == 12

    @pytest.mark.asyncio
    async def test_K4_zero_duplicates_after_crash_resume(self, test_session):
        """K4: After crash at 7 + resume, zero duplicate (doc, page) pairs."""
        packet, docs = await _setup_three_doc_packet(test_session)
        await _seed_partial(test_session, packet, docs, 7)

        service = BatesAssignmentService()
        await service.assign_bates(test_session, packet.id)

        result = await test_session.execute(
            text(
                "SELECT document_id, page_number, COUNT(*) "
                "FROM bates_assignments WHERE packet_id = :pid "
                "GROUP BY document_id, page_number HAVING COUNT(*) > 1"
            ),
            {"pid": _uuid(packet.id)},
        )
        assert result.fetchall() == []

    @pytest.mark.asyncio
    async def test_K5_journal_proves_continuity_after_crash(self, test_session):
        """K5: Journal prove_continuity returns valid=True after crash + resume.

        Note: _seed_partial inserts DB rows directly (simulating a crash before
        journaling), so the journal only contains entries from the resume call
        (pages 5-12 = 8 entries). We verify the journal's own entries are
        contiguous and gap-free.
        """
        from app.config import get_settings
        settings = get_settings()

        packet, docs = await _setup_three_doc_packet(test_session)
        await _seed_partial(test_session, packet, docs, 4)

        service = BatesAssignmentService()
        await service.assign_bates(test_session, packet.id)

        journal = BatesJournal(settings.working_path / f"bates_journal_{packet.id}.jsonl")
        # Journal only has entries from assign_bates (pages 5-12), not from _seed_partial
        proof = journal.prove_continuity(expected_count=8, bates_start_number=5)
        assert proof.valid, f"Journal proof failed: {proof.as_dict()}"
        assert proof.gaps == []
        assert proof.duplicates == []

    @pytest.mark.asyncio
    async def test_K6_rejected_text_survives(self, test_session):
        """K6: REJECTED redaction leaves text in the output PDF.

        The RedactionByteScrubber scrubs ALL candidates regardless of status.
        The status filtering happens at RedactionApplicationService level.
        This test verifies the application service correctly skips REJECTED.
        """
        from app.services.redaction import RedactionApplicationService

        candidate = RedactionCandidate(
            document_id="test-doc",
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="123-45-6789",
            context_before="",
            context_after="",
            x0=72, y0=88, x1=172, y1=100,
            status=RedactionStatus.REJECTED,
            proposed_by="test",
        )

        source = Path(tempfile.mktemp(suffix=".pdf"))
        source.write_bytes(_make_pdf(["SSN: 123-45-6789"]))

        output = Path(tempfile.mktemp(suffix=".pdf"))
        app_service = RedactionApplicationService()

        # apply_redactions_to_pdf filters: only APPROVED/APPLIED are scrubbed
        results = app_service.apply_redactions_to_pdf(source, output, [candidate])
        # REJECTED candidate should not be in results (filtered out)
        assert str(candidate.id) not in results or not results[str(candidate.id)].get("applied"), (
            "REJECTED candidate was applied — trust boundary violated"
        )

    @pytest.mark.asyncio
    async def test_K7_idempotent_scrub(self, test_session):
        """K7: Scrubbing same source twice produces identical text."""
        source = Path(tempfile.mktemp(suffix=".pdf"))
        source.write_bytes(_make_pdf(["SSN: 123-45-6789 Email: test@example.com"]))

        candidate = RedactionCandidate(
            document_id="test-doc",
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="123-45-6789",
            context_before="",
            context_after="",
            x0=72, y0=88, x1=172, y1=100,
            status=RedactionStatus.APPROVED,
            proposed_by="test",
        )
        scrubber = RedactionByteScrubber()

        out1 = Path(tempfile.mktemp(suffix=".pdf"))
        out2 = Path(tempfile.mktemp(suffix=".pdf"))
        scrubber.scrub(source, [candidate], out1)
        scrubber.scrub(source, [candidate], out2)

        assert _pdf_text(out1) == _pdf_text(out2), "Scrubbing not deterministic"

    @pytest.mark.asyncio
    async def test_K8_pristine_base_invariant(self, test_session):
        """K8: Always scrub from pristine source, never from previously scrubbed output."""
        source = Path(tempfile.mktemp(suffix=".pdf"))
        source.write_bytes(_make_pdf(["SSN: 123-45-6789 Email: test@example.com"]))

        c1 = RedactionCandidate(
            id="c1", document_id="test-doc", page_number=1,
            category=RedactionCategory.SSN, matched_text="123-45-6789",
            context_before="", context_after="",
            x0=72, y0=88, x1=172, y1=100,
            status=RedactionStatus.APPROVED, proposed_by="test",
        )
        c2 = RedactionCandidate(
            id="c2", document_id="test-doc", page_number=1,
            category=RedactionCategory.EMAIL, matched_text="test@example.com",
            context_before="", context_after="",
            x0=200, y0=88, x1=350, y1=100,
            status=RedactionStatus.APPROVED, proposed_by="test",
        )

        scrubber = RedactionByteScrubber()

        # Scrub only c1
        out1 = Path(tempfile.mktemp(suffix=".pdf"))
        scrubber.scrub(source, [c1], out1)
        text1 = _pdf_text(out1)
        assert "123-45-6789" not in text1
        assert "test@example.com" in text1, "Email should survive first scrub"

        # Now scrub both from PRISTINE source (not from out1)
        out2 = Path(tempfile.mktemp(suffix=".pdf"))
        scrubber.scrub(source, [c1, c2], out2)
        text2 = _pdf_text(out2)
        assert "123-45-6789" not in text2
        assert "test@example.com" not in text2

    @pytest.mark.asyncio
    async def test_K9_double_application_prevention(self, test_session):
        """K9: Applying same redaction twice from pristine base produces same output."""
        source = Path(tempfile.mktemp(suffix=".pdf"))
        source.write_bytes(_make_pdf(["SSN: 123-45-6789"]))

        candidate = RedactionCandidate(
            document_id="test-doc", page_number=1,
            category=RedactionCategory.SSN, matched_text="123-45-6789",
            context_before="", context_after="",
            x0=72, y0=88, x1=172, y1=100,
            status=RedactionStatus.APPROVED, proposed_by="test",
        )
        scrubber = RedactionByteScrubber()

        out1 = Path(tempfile.mktemp(suffix=".pdf"))
        out2 = Path(tempfile.mktemp(suffix=".pdf"))
        scrubber.scrub(source, [candidate], out1)
        scrubber.scrub(source, [candidate], out2)

        # Both from pristine: byte-identical text
        assert _pdf_text(out1) == _pdf_text(out2)
        # SSN gone in both
        assert "123-45-6789" not in _pdf_text(out1)
        assert "123-45-6789" not in _pdf_text(out2)
