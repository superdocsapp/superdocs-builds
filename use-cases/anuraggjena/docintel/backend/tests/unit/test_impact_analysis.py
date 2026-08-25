"""
Unit tests for ImpactAnalysisService.

Tests focused update detection and impact analysis logic.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock, patch

from backend.services.impact_analysis import (
    ImpactAnalysisService,
    ClaimImpact,
    ImpactAnalysisResult
)


class TestImpactAnalysisService:
    """Test ImpactAnalysisService."""

    @pytest.fixture
    def mock_repos(self):
        """Create mock repositories."""
        run_repo = Mock()
        claim_repo = Mock()
        doc_repo = Mock()
        chunk_repo = Mock()

        return {
            "run_repo": run_repo,
            "claim_repo": claim_repo,
            "doc_repo": doc_repo,
            "chunk_repo": chunk_repo
        }

    @pytest.fixture
    def service(self, mock_repos):
        """Create ImpactAnalysisService with mock repositories."""
        return ImpactAnalysisService(
            workflow_run_repo=mock_repos["run_repo"],
            claim_repo=mock_repos["claim_repo"],
            document_repo=mock_repos["doc_repo"],
            chunk_repo=mock_repos["chunk_repo"]
        )

    def test_hash_content(self, service):
        """Test content hashing is deterministic."""
        content1 = "This is a test"
        content2 = "This   is   a   test"  # Extra whitespace
        content3 = "This is another test"

        hash1 = service._hash_content(content1)
        hash2 = service._hash_content(content2)
        hash3 = service._hash_content(content3)

        # Same normalized content = same hash
        assert hash1 == hash2

        # Different content = different hash
        assert hash1 != hash3

    def test_identify_changed_chunks(self, service):
        """Test chunk change detection."""
        # Create baseline chunks
        baseline_chunks = [
            Mock(id=uuid4(), chunk_index=0, text="Unchanged content"),
            Mock(id=uuid4(), chunk_index=1, text="Will change"),
            Mock(id=uuid4(), chunk_index=2, text="Another unchanged")
        ]

        # Create new chunks (chunk 1 changed)
        new_chunks = [
            Mock(id=uuid4(), chunk_index=0, text="Unchanged content"),
            Mock(id=uuid4(), chunk_index=1, text="Changed content here"),
            Mock(id=uuid4(), chunk_index=2, text="Another unchanged")
        ]

        changed_ids = service._identify_changed_chunks(
            baseline_chunks,
            new_chunks
        )

        # Only chunk at index 1 should be changed
        assert len(changed_ids) == 1
        assert str(new_chunks[1].id) in changed_ids

    def test_identify_new_chunks(self, service):
        """Test new chunk detection."""
        baseline_chunks = [
            Mock(chunk_index=0, text="First chunk"),
            Mock(chunk_index=1, text="Second chunk")
        ]

        new_chunks = [
            Mock(id=uuid4(), chunk_index=0, text="First chunk"),
            Mock(id=uuid4(), chunk_index=1, text="Second chunk"),
            Mock(id=uuid4(), chunk_index=2, text="New chunk"),  # NEW
            Mock(id=uuid4(), chunk_index=3, text="Another new")  # NEW
        ]

        new_chunk_ids = service._identify_new_chunks(
            baseline_chunks,
            new_chunks
        )

        # Should find 2 new chunks
        assert len(new_chunk_ids) == 2
        assert str(new_chunks[2].id) in new_chunk_ids
        assert str(new_chunks[3].id) in new_chunk_ids

    @pytest.mark.asyncio
    async def test_detect_focused_update_same_filename(self, service, mock_repos):
        """Test focused update detection with same filename."""
        workspace_id = uuid4()
        new_document_id = uuid4()

        # Create new document
        new_doc = Mock(
            id=new_document_id,
            filename="invoice.pdf",
            checksum="new_checksum_123"
        )
        mock_repos["doc_repo"].get_by_id = AsyncMock(return_value=new_doc)

        # Create baseline run and document
        baseline_run_id = uuid4()
        baseline_run = Mock(id=baseline_run_id, status="completed")
        baseline_doc = Mock(
            id=uuid4(),
            filename="invoice.pdf",  # SAME filename
            checksum="old_checksum_456"  # DIFFERENT checksum
        )

        mock_repos["run_repo"].get_recent_successful_runs = AsyncMock(
            return_value=[baseline_run]
        )
        mock_repos["run_repo"].get_document_for_run = AsyncMock(
            return_value=baseline_doc
        )

        # Should detect focused update
        result = await service.detect_focused_update(
            new_document_id,
            workspace_id
        )

        assert result == baseline_run_id

    @pytest.mark.asyncio
    async def test_detect_focused_update_different_filename(self, service, mock_repos):
        """Test focused update NOT detected with different filename."""
        workspace_id = uuid4()
        new_document_id = uuid4()

        # Create new document
        new_doc = Mock(
            id=new_document_id,
            filename="new_invoice.pdf",
            checksum="new_checksum_123"
        )
        mock_repos["doc_repo"].get_by_id = AsyncMock(return_value=new_doc)

        # Create baseline run and document
        baseline_run = Mock(id=uuid4(), status="completed")
        baseline_doc = Mock(
            id=uuid4(),
            filename="old_invoice.pdf",  # DIFFERENT filename
            checksum="old_checksum_456"
        )

        mock_repos["run_repo"].get_recent_successful_runs = AsyncMock(
            return_value=[baseline_run]
        )
        mock_repos["run_repo"].get_document_for_run = AsyncMock(
            return_value=baseline_doc
        )

        # Should NOT detect focused update
        result = await service.detect_focused_update(
            new_document_id,
            workspace_id
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_detect_focused_update_same_checksum(self, service, mock_repos):
        """Test focused update NOT detected when content identical."""
        workspace_id = uuid4()
        new_document_id = uuid4()

        # Create new document
        new_doc = Mock(
            id=new_document_id,
            filename="invoice.pdf",
            checksum="same_checksum_123"
        )
        mock_repos["doc_repo"].get_by_id = AsyncMock(return_value=new_doc)

        # Create baseline run and document
        baseline_run = Mock(id=uuid4(), status="completed")
        baseline_doc = Mock(
            id=uuid4(),
            filename="invoice.pdf",  # SAME filename
            checksum="same_checksum_123"  # SAME checksum
        )

        mock_repos["run_repo"].get_recent_successful_runs = AsyncMock(
            return_value=[baseline_run]
        )
        mock_repos["run_repo"].get_document_for_run = AsyncMock(
            return_value=baseline_doc
        )

        # Should NOT detect focused update (same content)
        result = await service.detect_focused_update(
            new_document_id,
            workspace_id
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_update_impact_no_baseline_claims(self, service, mock_repos):
        """Test impact analysis with no baseline claims."""
        new_document_id = uuid4()
        baseline_run_id = uuid4()

        # No baseline claims
        mock_repos["claim_repo"].get_approved_claims_for_run = AsyncMock(
            return_value=[]
        )

        result = await service.analyze_update_impact(
            new_document_id,
            baseline_run_id
        )

        assert result.total_baseline_claims == 0
        assert result.unchanged_count == 0
        assert result.affected_count == 0
        assert result.new_count == 0

    # NOTE: _assess_claim_impact tests removed - they require database integration
    # to properly test Citation/Evidence relationships. Covered by integration tests.
