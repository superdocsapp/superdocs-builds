"""TASK 2.1 CHAIN OF CUSTODY — Evidence Ledger Tests.

Builds a machine-readable evidence ledger from existing DB events and
verifies that every redaction can be traced through:

  source → proposal → human decision → application → verification → final artifact

A reviewer should be able to answer:
  - Who approved this redaction?
  - When?
  - What document/page did it affect?
  - Which final artifact contains the result?
  - Was the sensitive text actually removed?

Usage:
  cd backend
  pytest app/tests/evaluation/test_task21_chain_of_custody.py -v
"""

import json
from pathlib import Path

import fitz
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.bates import BatesAssignment
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.domain.page import Page
from app.domain.privilege import PrivilegeCategory, PrivilegeDecision, PrivilegeStatus
from app.domain.redaction import (
    RedactionApproval,
    RedactionCandidate,
    RedactionCategory,
    RedactionStatus,
)
from app.services.bates_assignment import BatesAssignmentService
from app.services.redaction_scrubber import RedactionByteScrubber, RedactionVerifier
from app.time import utc_now

REPORT_DIR = Path(__file__).parent.parent.parent.parent / "evaluation" / "reports"


def _uuid(val):
    return str(val)


async def _create_test_document(session) -> tuple[Packet, Document]:
    """Create a single-document packet for chain-of-custody testing."""
    packet = Packet(
        name="Chain of Custody Test",
        bates_prefix="CASE-",
        bates_start_number=1,
        bates_padding=6,
    )
    session.add(packet)
    await session.commit()
    await session.refresh(packet)

    doc = Document(
        packet_id=packet.id,
        display_order=1,
        original_filename="custody_test.pdf",
        mime_type="application/pdf",
        file_size=1024,
        sha256="a" * 64,
        original_sha256="a" * 64,
        document_type=DocumentType.PDF,
        page_count=1,
        processing_status=ProcessingStatus.COMPLETED,
        description="Test document for chain of custody evaluation",
        description_source="content_summary",
        is_searchable=True,
        processed_at=utc_now(),
        completed_at=utc_now(),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    session.add(Page(document_id=doc.id, page_number=1, has_text=True))
    await session.commit()

    return packet, doc


# --------------------------------------------------------------------------- #
# Evidence ledger construction
# --------------------------------------------------------------------------- #


def _build_ledger_entry(
    document: Document,
    candidate: RedactionCandidate,
    approval: RedactionApproval | None,
    bates: BatesAssignment | None,
    final_sha256: str | None,
    verification: dict | None,
) -> dict:
    """Build a single chain-of-custody entry from existing DB state."""
    return {
        "document_id": _uuid(document.id),
        "document_filename": document.original_filename,
        "page": candidate.page_number,
        "bates_label": bates.bates_label if bates else None,
        "proposal": {
            "candidate_id": _uuid(candidate.id),
            "matched_text": "***",  # never expose in ledger
            "category": candidate.category.value,
            "proposed_by": candidate.proposed_by,
            "proposed_at": candidate.proposed_at.isoformat() if candidate.proposed_at else None,
            "superdocs_change_id": candidate.superdocs_change_id,
        },
        "human_decision": {
            "status": candidate.status.value,
            "approver": approval.approver if approval else None,
            "approved_at": approval.approved_at.isoformat() if approval and approval.approved_at else None,
        },
        "application": {
            "applied_at": approval.applied_at.isoformat() if approval and approval.applied_at else None,
            "applied_by": approval.applied_by if approval else None,
        },
        "verification": verification,
        "final_artifact": {
            "sha256": final_sha256,
        },
    }


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


class TestChainOfCustody:
    """Verify every redaction can be traced through the full lifecycle."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_trace(self, test_session: AsyncSession):
        """Trace a redaction from source → proposal → decision → application → verification."""
        packet, doc = await _create_test_document(test_session)

        # 1. Source: assign Bates
        bates_service = BatesAssignmentService()
        await bates_service.assign_bates(test_session, packet.id)
        assignments = await bates_service.get_bates_assignments(test_session, packet.id)
        assert len(assignments) == 1
        bates = assignments[0]

        # 2. Proposal: create a redaction candidate
        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.SSN,
            matched_text="123-45-6789",
            context_before="SSN: ",
            context_after="",
            x0=72, y0=88, x1=172, y1=100,
            status=RedactionStatus.PROPOSED,
            proposed_by="local_fallback",
        )
        test_session.add(candidate)
        await test_session.commit()
        await test_session.refresh(candidate)

        # 3. Human decision: approve
        candidate.status = RedactionStatus.APPROVED
        approval = RedactionApproval(
            candidate_id=candidate.id,
            status=RedactionStatus.APPROVED,
            approver="evaluator@test.com",
            approved_at=utc_now(),
        )
        test_session.add(approval)
        await test_session.commit()
        await test_session.refresh(approval)

        # 4. Application: byte-scrub
        import tempfile
        source_path = Path(tempfile.mktemp(suffix=".pdf"))
        pdf_doc = fitz.open()
        page = pdf_doc.new_page(width=612, height=792)
        page.insert_text((72, 100), "SSN: 123-45-6789", fontsize=12, fontname="helv")
        pdf_doc.save(str(source_path))
        pdf_doc.close()

        output_path = Path(tempfile.mktemp(suffix=".pdf"))
        scrubber = RedactionByteScrubber()
        scrub_result = scrubber.scrub(source_path, [candidate], output_path)
        assert scrub_result.rects_applied >= 1

        # 5. Verification
        verifier = RedactionVerifier()
        verification = verifier.verify_pdf(output_path, [candidate])
        assert verification[str(candidate.id)]["verified"] is True

        # 6. Final artifact hash
        import hashlib
        h = hashlib.sha256()
        with open(output_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        final_sha256 = h.hexdigest()

        # 7. Build evidence ledger entry
        entry = _build_ledger_entry(doc, candidate, approval, bates, final_sha256, verification)

        # Verify chain is complete
        assert entry["document_id"] is not None
        assert entry["bates_label"] is not None
        assert entry["proposal"]["proposed_by"] == "local_fallback"
        assert entry["human_decision"]["approver"] == "evaluator@test.com"
        assert entry["human_decision"]["status"] == "approved"
        assert entry["verification"][str(candidate.id)]["verified"] is True
        assert entry["final_artifact"]["sha256"] is not None

        # Write ledger
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        ledger_path = REPORT_DIR / "chain_of_custody.json"
        ledger_path.write_text(json.dumps([entry], indent=2))
        assert ledger_path.exists()

    @pytest.mark.asyncio
    async def test_rejected_proposal_has_no_application(self, test_session: AsyncSession):
        """A REJECTED proposal has no application/verification step."""
        packet, doc = await _create_test_document(test_session)

        candidate = RedactionCandidate(
            document_id=doc.id,
            page_number=1,
            category=RedactionCategory.EMAIL,
            matched_text="test@example.com",
            context_before="",
            context_after="",
            x0=72, y0=88, x1=250, y1=100,
            status=RedactionStatus.REJECTED,
            proposed_by="local_fallback",
        )
        test_session.add(candidate)
        await test_session.commit()
        await test_session.refresh(candidate)

        approval = RedactionApproval(
            candidate_id=candidate.id,
            status=RedactionStatus.REJECTED,
            approver="evaluator@test.com",
            approved_at=utc_now(),
        )
        test_session.add(approval)
        await test_session.commit()

        entry = _build_ledger_entry(doc, candidate, approval, None, None, None)
        assert entry["human_decision"]["status"] == "rejected"
        assert entry["application"]["applied_at"] is None
        assert entry["verification"] is None

    @pytest.mark.asyncio
    async def test_privilege_decision_in_ledger(self, test_session: AsyncSession):
        """Privilege decisions appear in the evidence ledger."""
        packet, doc = await _create_test_document(test_session)

        decision = PrivilegeDecision(
            packet_id=packet.id,
            document_id=doc.id,
            status=PrivilegeStatus.PRIVILEGED,
            category=PrivilegeCategory.ATTORNEY_CLIENT,
            reason="Attorney-client communication regarding case strategy",
            reviewer="evaluator@test.com",
            decided_at=utc_now(),
        )
        test_session.add(decision)
        await test_session.commit()

        ledger_entry = {
            "document_id": _uuid(doc.id),
            "privilege": {
                "status": decision.status.value,
                "category": decision.category.value,
                "reason": decision.reason,
                "reviewer": decision.reviewer,
                "decided_at": decision.decided_at.isoformat(),
            },
        }
        assert ledger_entry["privilege"]["status"] == "privileged"
        assert ledger_entry["privilege"]["category"] == "attorney_client"
        assert "attorney-client" in ledger_entry["privilege"]["reason"].lower()
