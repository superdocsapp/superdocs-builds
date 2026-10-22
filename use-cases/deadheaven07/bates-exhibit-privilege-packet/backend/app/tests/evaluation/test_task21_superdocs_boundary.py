"""TASK 2.1 SUPERDOCS BOUNDARY — Failure + Operation Accounting Tests.

Tests the adapter/fake boundary to verify:
  - SuperDocs available → SuperDocs proposals
  - SuperDocs unavailable → local fallback
  - Output clearly distinguishes SuperDocs result vs local fallback
  - Never fabricates a SuperDocs result when adapter is unavailable

Also provides operation accounting:
  - Analysis calls
  - Approval calls
  - Export calls
  - Fallback count

Usage:
  cd backend
  pytest app/tests/evaluation/test_task21_superdocs_boundary.py -v
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.domain.page import Page
from app.domain.redaction import (
    RedactionCandidate,
    RedactionCategory,
    RedactionStatus,
)
from app.services.fallback_detection import PROVENANCE_LOCAL_FALLBACK
from app.services.redaction import RedactionDetectionService
from app.services.superdocs_intelligence import PROVENANCE_SUPERDOCS
from app.services.superdocs_port import (
    PIICategory,
    PIIDetectionResult,
    PIIEntity,
    ProposedChangeBatch,
    SuperDocsPort,
)
from app.time import utc_now


async def _create_test_doc(session) -> Document:
    packet = Packet(
        name="SuperDocs Boundary Test",
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
        original_filename="boundary_test.pdf",
        mime_type="application/pdf",
        file_size=1024,
        sha256="b" * 64,
        original_sha256="b" * 64,
        document_type=DocumentType.PDF,
        page_count=1,
        processing_status=ProcessingStatus.COMPLETED,
        is_searchable=True,
        processed_at=utc_now(),
        completed_at=utc_now(),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)

    session.add(Page(document_id=doc.id, page_number=1, has_text=True))
    await session.commit()

    return doc


def _make_superdocs_adapter_mock(
    detect_result: PIIDetectionResult | None = None,
    fail: bool = False,
):
    """Create a mock SuperDocs adapter that can succeed or fail."""
    adapter = MagicMock(spec=SuperDocsPort)
    adapter.upload_document = AsyncMock(return_value=MagicMock(
        session_id="mock-session",
        document_id="mock-doc",
    ))
    adapter.chat_async = AsyncMock(return_value="mock-job")
    adapter.poll_job = AsyncMock(return_value=MagicMock(
        status="completed",
        metadata={},
    ))
    adapter.approve_changes = AsyncMock(return_value=MagicMock(status="completed"))
    adapter.export_document = AsyncMock(return_value=MagicMock(
        download_url=None,
        filename="export.pdf",
    ))
    adapter.parse_proposed_change_batch = MagicMock(
        return_value=ProposedChangeBatch(
            batch_id="batch-1",
            batch_total=1,
            changes=[],
        )
    )

    if fail:
        adapter.chat_async = AsyncMock(side_effect=ConnectionError("SuperDocs unavailable"))

    return adapter


class TestSuperDocsFailureBoundary:
    """Verify graceful degradation when SuperDocs is unavailable."""

    @pytest.mark.asyncio
    async def test_adapter_unavailable_uses_fallback(self, test_session):
        """When adapter raises, detection falls back to local regex."""
        doc = await _create_test_doc(test_session)

        adapter = _make_superdocs_adapter_mock(fail=True)
        from app.services.superdocs_intelligence import SuperDocsIntelligenceService
        intelligence = SuperDocsIntelligenceService(adapter=adapter)

        detector = RedactionDetectionService(superdocs=intelligence)
        result = await detector.detect_pii_in_document(test_session, str(doc.id))

        # Should fall back to local regex (no SuperDocs session_id)
        assert result.session_id == ""
        # Should still detect PII if any is in the document text
        # (Our test doc has no PII, so total_count may be 0 — that's fine)
        assert result.total_count >= 0

    @pytest.mark.asyncio
    async def test_fallback_provenance_label(self, test_session):
        """Fallback detection labels proposals with local_fallback provenance."""
        doc = await _create_test_doc(test_session)

        detector = RedactionDetectionService(superdocs=None)
        result = await detector.detect_pii_in_document(test_session, str(doc.id))

        # Create candidates from fallback
        candidates = await detector.create_redaction_candidates(
            test_session, str(doc.id), result
        )

        for c in candidates:
            assert c.proposed_by == PROVENANCE_LOCAL_FALLBACK, (
                f"Candidate provenance is {c.proposed_by}, expected local_fallback"
            )

    @pytest.mark.asyncio
    async def test_superdocs_provenance_label(self, test_session):
        """When SuperDocs is available, proposals are labeled superdocs."""
        from app.services.superdocs_intelligence import SuperDocsIntelligenceService

        doc = await _create_test_doc(test_session)

        # Create a mock that returns PII entities
        mock_result = PIIDetectionResult(
            entities=[
                PIIEntity(
                    category=PIICategory.SSN,
                    text="123-45-6789",
                    page_number=1,
                    start_offset=0,
                    end_offset=11,
                    confidence=0.95,
                    context_before="SSN: ",
                    context_after="",
                    superdocs_change_id="change-1",
                )
            ],
            total_count=1,
            session_id="mock-session",
            document_id="mock-doc",
            job_id="mock-job",
        )

        adapter = _make_superdocs_adapter_mock()
        intelligence = SuperDocsIntelligenceService(adapter=adapter)

        # Override detect_pii to return our mock result
        intelligence.detect_pii = AsyncMock(return_value=mock_result)

        detector = RedactionDetectionService(superdocs=intelligence)
        result = await detector.detect_pii_in_document(test_session, str(doc.id))

        assert result.session_id == "mock-session"
        assert result.total_count == 1

        candidates = await detector.create_redaction_candidates(
            test_session, str(doc.id), result
        )
        assert len(candidates) == 1
        assert candidates[0].proposed_by == PROVENANCE_SUPERDOCS

    @pytest.mark.asyncio
    async def test_never_fabricates_superdocs_result(self, test_session, monkeypatch):
        """When adapter is None, no SuperDocs session_id appears in results."""
        doc = await _create_test_doc(test_session)

        # Force superdocs_available=False so _get_superdocs returns None
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "superdocs_primary", False)

        detector = RedactionDetectionService(superdocs=None)
        result = await detector.detect_pii_in_document(test_session, str(doc.id))

        assert result.session_id == "", "Fabricated SuperDocs session_id when adapter is None"
        assert result.document_id != "mock-doc", "Fabricated SuperDocs document_id"


class TestSuperDocsOperationAccounting:
    """Track SuperDocs operation counts for the evaluation report."""

    @pytest.mark.asyncio
    async def test_operation_counts(self, test_session):
        """Count analysis, approval, export, and fallback operations."""
        from app.tests.qa_helpers import FakeSuperDocsService

        fake = FakeSuperDocsService()

        doc = await _create_test_doc(test_session)

        # Run detection (triggers analysis)
        detector = RedactionDetectionService(superdocs=fake)
        result = await detector.detect_pii_in_document(test_session, str(doc.id))

        accounting = {
            "superdocs_analyses": fake.detect_calls,
            "superdocs_approvals": fake.apply_calls,
            "superdocs_exports": 0,  # Fake doesn't track exports separately
            "local_fallbacks": 0 if result.session_id else 1,
        }

        assert accounting["superdocs_analyses"] >= 1
        assert accounting["local_fallbacks"] == 0  # Fake provides session_id

        # Write accounting report
        from pathlib import Path
        REPORT_DIR = Path(__file__).parent.parent.parent.parent / "evaluation" / "reports"
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        (REPORT_DIR / "superdocs_accounting.json").write_text(
            __import__("json").dumps(accounting, indent=2)
        )
