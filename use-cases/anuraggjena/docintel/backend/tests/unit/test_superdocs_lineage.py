"""
Unit tests for SuperDocs lineage functionality.

Tests that SuperDocs approval creates proper lineage links.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, Mock
from datetime import datetime, timezone

from backend.integrations.superdocs.approval_handler import ApprovalHandler


class TestSuperDocsLineage:
    """Test SuperDocs lineage creation."""

    @pytest.fixture
    def mock_claim(self):
        """Create mock claim with SuperDocs metadata."""
        claim = Mock(
            id=uuid4(),
            workflow_run_id=uuid4(),
            claim_type="superdocs_change",
            content='{"superdocs_change_id": "change_123", "chunk_id": "chunk_456", "ai_explanation": "Update title", "new_html": "<h1>New</h1>", "old_html": "<h1>Old</h1>"}',
            status="approved",
            superdocs_change_id="change_123",
            superdocs_job_id="job_789",
            updated_at=datetime.now(timezone.utc)
        )
        return claim

    @pytest.fixture
    def mock_repos(self):
        """Create mock repositories."""
        superdocs_client = Mock()
        session_manager = Mock()
        claim_repo = Mock()
        lineage_repo = Mock()

        lineage_repo.create_link = AsyncMock()

        return {
            "superdocs_client": superdocs_client,
            "session_manager": session_manager,
            "claim_repo": claim_repo,
            "lineage_repo": lineage_repo
        }

    @pytest.fixture
    def handler(self, mock_repos):
        """Create ApprovalHandler with mocked dependencies."""
        return ApprovalHandler(
            superdocs_client=mock_repos["superdocs_client"],
            session_manager=mock_repos["session_manager"],
            claim_repository=mock_repos["claim_repo"],
            lineage_repository=mock_repos["lineage_repo"]
        )

    @pytest.mark.asyncio
    async def test_approved_change_creates_lineage(self, handler, mock_claim, mock_repos):
        """Test that approved SuperDocs changes create lineage links."""
        session_id = "session_abc"

        await handler._create_lineage_link(mock_claim, session_id=session_id)

        # Verify lineage link was created
        assert mock_repos["lineage_repo"].create_link.called
        call_kwargs = mock_repos["lineage_repo"].create_link.call_args.kwargs

        # Verify link type and IDs
        assert call_kwargs["link_type"] == "superdocs_edit"
        assert call_kwargs["source_type"] == "claim"
        assert call_kwargs["source_id"] == mock_claim.id
        assert call_kwargs["workflow_run_id"] == mock_claim.workflow_run_id
        assert call_kwargs["stage_name"] == "superdocs_approval"

        # Verify metadata includes SuperDocs context
        metadata = call_kwargs["metadata"]
        assert metadata["change_approved"] is True
        assert metadata["job_id"] == "job_789"
        assert metadata["change_id"] == "change_123"
        assert metadata["session_id"] == session_id
        assert metadata["chunk_id"] == "chunk_456"
        assert metadata["ai_explanation"] == "Update title"
        assert metadata["timestamp"] is not None

    @pytest.mark.asyncio
    async def test_lineage_without_session_id(self, handler, mock_claim, mock_repos):
        """Test lineage creation without session_id."""
        await handler._create_lineage_link(mock_claim, session_id=None)

        assert mock_repos["lineage_repo"].create_link.called
        call_kwargs = mock_repos["lineage_repo"].create_link.call_args.kwargs

        metadata = call_kwargs["metadata"]
        assert "session_id" not in metadata

    @pytest.mark.asyncio
    async def test_lineage_skipped_when_no_repo(self, mock_claim):
        """Test that lineage creation is skipped when no repository."""
        handler = ApprovalHandler(
            superdocs_client=Mock(),
            session_manager=Mock(),
            claim_repository=Mock(),
            lineage_repository=None  # No lineage repo
        )

        # Should not raise exception
        await handler._create_lineage_link(mock_claim)

    @pytest.mark.asyncio
    async def test_lineage_handles_invalid_content(self, mock_repos):
        """Test lineage creation with invalid claim content."""
        claim = Mock(
            id=uuid4(),
            workflow_run_id=uuid4(),
            content="invalid json {",
            superdocs_change_id="change_123",
            superdocs_job_id="job_789",
            updated_at=datetime.now(timezone.utc)
        )

        handler = ApprovalHandler(
            superdocs_client=mock_repos["superdocs_client"],
            session_manager=mock_repos["session_manager"],
            claim_repository=mock_repos["claim_repo"],
            lineage_repository=mock_repos["lineage_repo"]
        )

        # Should not raise exception
        await handler._create_lineage_link(claim)

        # Lineage should still be created (without chunk_id/description)
        assert mock_repos["lineage_repo"].create_link.called

    @pytest.mark.asyncio
    async def test_lineage_content_extraction(self, handler, mock_repos):
        """Test that lineage extracts content correctly from claim."""
        claim = Mock(
            id=uuid4(),
            workflow_run_id=uuid4(),
            content='{"chunk_id": "chunk_789", "ai_explanation": "Fix typo"}',
            superdocs_change_id="change_456",
            superdocs_job_id="job_123",
            updated_at=datetime.now(timezone.utc)
        )

        await handler._create_lineage_link(claim, session_id="session_xyz")

        call_kwargs = mock_repos["lineage_repo"].create_link.call_args.kwargs
        metadata = call_kwargs["metadata"]

        assert metadata["chunk_id"] == "chunk_789"
        assert metadata["ai_explanation"] == "Fix typo"
        assert metadata["change_id"] == "change_456"
