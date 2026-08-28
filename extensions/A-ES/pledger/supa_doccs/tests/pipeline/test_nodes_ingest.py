"""Unit tests for the ingest pipeline node."""

import uuid
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline.nodes.ingest import (
    ALLOWED_MIME_TYPES,
    StorageReader,
    ingest,
)
from src.pipeline.state import PipelineState, create_initial_state


# --- Fixtures and Helpers ---


def _make_state(
    document_id: Optional[str] = None,
    document_version_id: Optional[str] = None,
) -> PipelineState:
    """Create a minimal initial state for testing the ingest node."""
    from src.pipeline.config import load_config

    config = load_config()
    return create_initial_state(
        run_id=str(uuid.uuid4()),
        document_id=document_id or str(uuid.uuid4()),
        document_version_id=document_version_id or str(uuid.uuid4()),
        config=config,
    )


class FakeStorageReader:
    """A fake storage reader for testing that returns preconfigured content."""

    def __init__(self, content: Optional[bytes] = None):
        self._content = content

    def read(self, storage_ref: str) -> Optional[bytes]:
        return self._content


def _mock_db_session(
    *,
    storage_ref: str = "/tmp/test.pdf",
    mime_type: str = "application/pdf",
    version_exists: bool = True,
):
    """Create a mock SQLAlchemy session that returns a document version."""
    session = MagicMock()

    if version_exists:
        version_row = MagicMock()
        version_row.storage_ref = storage_ref
        version_row.document.mime_type = mime_type

        result = MagicMock()
        result.scalar_one_or_none.return_value = version_row
        session.execute.return_value = result
    else:
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

    return session


# --- Test Classes ---


class TestIngestSuccess:
    """Tests for successful document ingestion."""

    @pytest.mark.anyio
    async def test_ingest_pdf_success(self):
        """Ingest a valid PDF document successfully."""
        state = _make_state()
        content = b"%PDF-1.4 fake pdf content"
        db_session = _mock_db_session(mime_type="application/pdf")
        storage_reader = FakeStorageReader(content)

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "completed"
        assert result["current_node"] == "ingest"
        assert result["raw_content"] == content
        assert result["mime_type"] == "application/pdf"
        assert result["error_type"] is None
        assert result["error_detail"] is None

    @pytest.mark.anyio
    async def test_ingest_docx_success(self):
        """Ingest a valid DOCX document successfully."""
        state = _make_state()
        content = b"PK\x03\x04 fake docx content"
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        db_session = _mock_db_session(mime_type=mime)
        storage_reader = FakeStorageReader(content)

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "completed"
        assert result["mime_type"] == mime
        assert result["raw_content"] == content

    @pytest.mark.anyio
    async def test_ingest_plain_text_success(self):
        """Ingest a valid plain text document successfully."""
        state = _make_state()
        content = b"Hello, this is a plain text document."
        db_session = _mock_db_session(mime_type="text/plain")
        storage_reader = FakeStorageReader(content)

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "completed"
        assert result["mime_type"] == "text/plain"
        assert result["raw_content"] == content

    @pytest.mark.anyio
    async def test_completed_nodes_includes_ingest(self):
        """On success, completed_nodes should include 'ingest'."""
        state = _make_state()
        content = b"some content"
        db_session = _mock_db_session(mime_type="text/plain")
        storage_reader = FakeStorageReader(content)

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert "ingest" in result["completed_nodes"]

    @pytest.mark.anyio
    async def test_completed_nodes_appends_to_existing(self):
        """Completed nodes should append to any pre-existing entries."""
        state = _make_state()
        # Simulate a state with pre-existing completed nodes
        state["completed_nodes"] = ["previous_node"]
        content = b"some content"
        db_session = _mock_db_session(mime_type="text/plain")
        storage_reader = FakeStorageReader(content)

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["completed_nodes"] == ["previous_node", "ingest"]


class TestIngestInvalidMimeType:
    """Tests for MIME type validation errors."""

    @pytest.mark.anyio
    async def test_error_on_invalid_mime_type(self):
        """Return permanent error for unsupported MIME type."""
        state = _make_state()
        content = b"<html>not a supported format</html>"
        db_session = _mock_db_session(mime_type="text/html")
        storage_reader = FakeStorageReader(content)

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert "Invalid MIME type" in result["error_detail"]
        assert "text/html" in result["error_detail"]

    @pytest.mark.anyio
    async def test_error_on_image_mime_type(self):
        """Return permanent error for image MIME type."""
        state = _make_state()
        content = b"\x89PNG image data"
        db_session = _mock_db_session(mime_type="image/png")
        storage_reader = FakeStorageReader(content)

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"

    @pytest.mark.anyio
    async def test_error_preserves_state_keys(self):
        """Error state should preserve identity keys from input."""
        state = _make_state()
        db_session = _mock_db_session(mime_type="application/zip")
        storage_reader = FakeStorageReader(b"zip content")

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["run_id"] == state["run_id"]
        assert result["document_id"] == state["document_id"]
        assert result["document_version_id"] == state["document_version_id"]


class TestIngestZeroBytes:
    """Tests for zero-byte content errors."""

    @pytest.mark.anyio
    async def test_error_on_zero_byte_content(self):
        """Return permanent error when storage returns empty bytes."""
        state = _make_state()
        db_session = _mock_db_session(mime_type="application/pdf")
        storage_reader = FakeStorageReader(b"")

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert "zero bytes" in result["error_detail"]

    @pytest.mark.anyio
    async def test_zero_bytes_does_not_add_to_completed_nodes(self):
        """Zero-byte error should not append to completed_nodes."""
        state = _make_state()
        db_session = _mock_db_session(mime_type="application/pdf")
        storage_reader = FakeStorageReader(b"")

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert "ingest" not in result["completed_nodes"]


class TestIngestUnreadableFile:
    """Tests for unreadable file / storage not found errors."""

    @pytest.mark.anyio
    async def test_error_on_storage_not_found(self):
        """Return permanent error when storage reader returns None."""
        state = _make_state()
        db_session = _mock_db_session(mime_type="application/pdf")
        storage_reader = FakeStorageReader(None)  # Simulates unreadable file

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert "Unable to read document" in result["error_detail"]

    @pytest.mark.anyio
    async def test_error_on_document_version_not_found(self):
        """Return permanent error when document version doesn't exist in DB."""
        state = _make_state()
        db_session = _mock_db_session(version_exists=False)

        result = await ingest(state, db_session=db_session)

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert "not found" in result["error_detail"]

    @pytest.mark.anyio
    async def test_error_when_no_session_or_reader(self):
        """Return permanent error when neither db_session nor reader is provided."""
        state = _make_state()

        result = await ingest(state)

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert "No database session" in result["error_detail"]


class TestIngestErrorStateConsistency:
    """Tests that error states have consistent structure."""

    @pytest.mark.anyio
    async def test_error_node_status_and_type_on_invalid_mime(self):
        """node_status='error' and error_type='permanent' on invalid MIME."""
        state = _make_state()
        db_session = _mock_db_session(mime_type="video/mp4")
        storage_reader = FakeStorageReader(b"video data")

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert result["current_node"] == "ingest"

    @pytest.mark.anyio
    async def test_error_node_status_and_type_on_zero_bytes(self):
        """node_status='error' and error_type='permanent' on zero bytes."""
        state = _make_state()
        db_session = _mock_db_session(mime_type="text/plain")
        storage_reader = FakeStorageReader(b"")

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert result["current_node"] == "ingest"

    @pytest.mark.anyio
    async def test_error_node_status_and_type_on_unreadable(self):
        """node_status='error' and error_type='permanent' on unreadable file."""
        state = _make_state()
        db_session = _mock_db_session(mime_type="application/pdf")
        storage_reader = FakeStorageReader(None)

        result = await ingest(
            state, db_session=db_session, storage_reader=storage_reader
        )

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert result["current_node"] == "ingest"
