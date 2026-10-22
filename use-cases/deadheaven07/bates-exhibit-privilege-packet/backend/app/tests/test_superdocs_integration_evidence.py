"""Integration evidence: prove the SuperDocs adapter is actually called.

These tests verify that when the SuperDocs adapter is wired in, the
intelligence layer delegates to the adapter (rather than silently falling back).
They use a mock adapter with call-tracking to provide concrete evidence of
real platform integration.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.document import Document, ProcessingStatus
from app.domain.packet import Packet
from app.services.superdocs_adapter import SuperDocsRESTAdapter
from app.services.superdocs_intelligence import SuperDocsIntelligenceService
from app.services.superdocs_port import (
    JobStatus,
    ProposedChangeBatch,
)


@pytest_asyncio.fixture
async def mock_adapter():
    """Adapter stub that records every method call."""
    adapter = AsyncMock(spec=SuperDocsRESTAdapter)

    adapter.upload_document.return_value = MagicMock(
        session_id="test-session-1",
        document_id="test-doc-1",
        chunks_count=5,
        version_id="v1",
        page_setup={},
        html=None,
    )

    adapter.chat_async.return_value = "job-001"

    adapter.poll_job.return_value = JobStatus(
        job_id="job-001",
        status="awaiting_approval",
        metadata={
            "pending_changes": {
                "type": "proposed_change_batch",
                "content": json.dumps(
                    {
                        "type": "single_approval",
                        "batch_id": "batch-1",
                        "batch_total": 1,
                        "changes": [
                            {
                                "change_id": "ch_001",
                                "operation": "replace",
                                "old_html": "<p>555-0123</p>",
                                "new_html": "<p>[REDACTED]</p>",
                                "ai_explanation": "PII|phone|555-0123|1",
                            }
                        ],
                        "awaiting_kind": "approval",
                    }
                ),
            }
        },
    )

    adapter.parse_proposed_change_batch.return_value = ProposedChangeBatch(
        batch_id="batch-1",
        batch_total=1,
        changes=[],
    )

    return adapter


@pytest_asyncio.fixture
async def db_session(test_engine):
    session_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_analyze_document_delegates_to_adapter_chat(
    mock_adapter, db_session, tmp_path
):
    """Evidence: when adapter is available, analyze_document calls adapter.chat_async."""
    packet = Packet(name="Integration Test Packet")
    db_session.add(packet)
    await db_session.flush()

    doc = Document(
        packet_id=packet.id,
        display_order=1,
        original_filename="contract.pdf",
        mime_type="application/pdf",
        file_size=1024,
        sha256="abc123",
        original_sha256="abc123",
        page_count=1,
        processing_status=ProcessingStatus.COMPLETED,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    intelligence = SuperDocsIntelligenceService(adapter=mock_adapter)

    with patch.object(
        intelligence, "_ensure_uploaded", new_callable=AsyncMock
    ):
        doc.superdocs_session_id = "test-session-1"
        await intelligence.analyze_document(db_session, doc)

    mock_adapter.chat_async.assert_called_once()
    call_kwargs = mock_adapter.chat_async.call_args
    assert call_kwargs.kwargs.get("session_id") == "test-session-1"
    assert call_kwargs.kwargs.get("approval_mode") == "ask_every_time"


@pytest.mark.asyncio
async def test_analyze_document_polls_until_terminal(
    mock_adapter, db_session, tmp_path
):
    """Evidence: analyze_document polls adapter.poll_job until terminal state."""
    packet = Packet(name="Poll Test Packet")
    db_session.add(packet)
    await db_session.flush()

    doc = Document(
        packet_id=packet.id,
        display_order=1,
        original_filename="memo.pdf",
        mime_type="application/pdf",
        file_size=1024,
        sha256="def456",
        original_sha256="def456",
        page_count=1,
        processing_status=ProcessingStatus.COMPLETED,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    intelligence = SuperDocsIntelligenceService(
        adapter=mock_adapter, poll_interval=0, max_polls=3
    )

    mock_adapter.poll_job.side_effect = [
        JobStatus(job_id="job-001", status="processing"),
        JobStatus(job_id="job-001", status="completed"),
    ]

    with patch.object(intelligence, "_ensure_uploaded", new_callable=AsyncMock):
        doc.superdocs_session_id = "test-session-1"
        await intelligence.analyze_document(db_session, doc)

    assert mock_adapter.poll_job.call_count == 2


@pytest.mark.asyncio
async def test_sibling_documents_enrich_instruction(
    mock_adapter, db_session, tmp_path
):
    """Evidence: when siblings are passed, the instruction is enriched with packet context."""
    packet = Packet(name="Sibling Test")
    db_session.add(packet)
    await db_session.flush()

    doc1 = Document(
        packet_id=packet.id,
        display_order=1,
        original_filename="exhibit_a.pdf",
        mime_type="application/pdf",
        file_size=512,
        sha256="aaa",
        original_sha256="aaa",
        page_count=2,
        processing_status=ProcessingStatus.COMPLETED,
    )
    doc2 = Document(
        packet_id=packet.id,
        display_order=2,
        original_filename="exhibit_b.pdf",
        mime_type="application/pdf",
        file_size=512,
        sha256="bbb",
        original_sha256="bbb",
        page_count=3,
        processing_status=ProcessingStatus.COMPLETED,
    )
    db_session.add_all([doc1, doc2])
    await db_session.commit()
    await db_session.refresh(doc1)
    await db_session.refresh(doc2)

    intelligence = SuperDocsIntelligenceService(adapter=mock_adapter)

    with patch.object(intelligence, "_ensure_uploaded", new_callable=AsyncMock):
        doc1.superdocs_session_id = "test-session-1"
        await intelligence.analyze_document(
            db_session, doc1, sibling_documents=[doc2]
        )

    call_kwargs = mock_adapter.chat_async.call_args
    instruction = call_kwargs.kwargs.get("message") or call_kwargs.args[0]
    assert "exhibit_b.pdf" in instruction
    assert "litigation packet" in instruction


@pytest.mark.asyncio
async def test_detect_pii_returns_provenance_superdocs(mock_adapter, db_session, tmp_path):
    """Evidence: when SuperDocs succeeds, PIIDetectionResult has session_id set (provenance=superdocs)."""
    from app.services.superdocs_port import PIIDetectionResult

    packet = Packet(name="Provenance Test")
    db_session.add(packet)
    await db_session.flush()

    doc = Document(
        packet_id=packet.id,
        display_order=1,
        original_filename="contract.pdf",
        mime_type="application/pdf",
        file_size=1024,
        sha256="ccc",
        original_sha256="ccc",
        page_count=1,
        processing_status=ProcessingStatus.COMPLETED,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)

    intelligence = SuperDocsIntelligenceService(adapter=mock_adapter)

    with patch.object(intelligence, "_ensure_uploaded", new_callable=AsyncMock):
        doc.superdocs_session_id = "test-session-1"
        result = await intelligence.detect_pii(db_session, doc)

    assert isinstance(result, PIIDetectionResult)
    assert result.session_id == "test-session-1"
    assert result.job_id == "job-001"
