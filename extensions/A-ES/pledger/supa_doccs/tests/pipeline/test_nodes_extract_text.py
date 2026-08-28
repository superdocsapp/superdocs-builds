"""Unit tests for the extract_text pipeline node.

Tests cover:
- Skip when mime_type is "text/plain" (raw_content decoded as UTF-8 → extracted_text)
- Successful text extraction from PDF (mocked)
- Successful text extraction from DOCX (mocked)
- Permanent error on corrupted file
- Transient error on timeout
- That skipped_nodes is populated correctly on skip
- That completed_nodes includes "extract_text" on success/skip
"""

import asyncio

import pytest

from src.pipeline.nodes.extract_text import extract_text
from src.pipeline.state import PipelineState, SkippedNodeEntry, create_initial_state


def _make_state(
    mime_type: str = "text/plain",
    raw_content: bytes | None = b"hello world",
    **overrides,
) -> PipelineState:
    """Create a minimal PipelineState for testing extract_text."""
    config = {
        "max_retries": 3,
        "chunk_max_size": 1000,
        "chunk_overlap": 200,
        "confidence_threshold": 0.7,
        "review_timeout_hours": 72,
        "reminder_interval_hours": 24,
        "poll_interval_seconds": 30,
        "extract_text_timeout_seconds": 60,
        "min_chunk_threshold": 200,
    }
    state = create_initial_state(
        run_id="test-run-001",
        document_id="test-doc-001",
        document_version_id="test-version-001",
        config=config,
    )
    state["raw_content"] = raw_content
    state["mime_type"] = mime_type
    state["current_node"] = "ingest"
    state["node_status"] = "completed"
    state["completed_nodes"] = ["ingest"]
    for key, value in overrides.items():
        state[key] = value  # type: ignore[literal-required]
    return state


# --- Skip Tests ---


@pytest.mark.anyio
async def test_skip_when_mime_type_text_plain():
    """When mime_type is text/plain, node should skip and decode raw_content as UTF-8."""
    state = _make_state(mime_type="text/plain", raw_content=b"Hello, world!")
    result = await extract_text(state)

    assert result["node_status"] == "skipped"
    assert result["current_node"] == "extract_text"
    assert result["extracted_text"] == "Hello, world!"
    assert result["error_type"] is None
    assert result["error_detail"] is None


@pytest.mark.anyio
async def test_skip_text_plain_utf8_encoding():
    """Skip path correctly decodes UTF-8 content including non-ASCII."""
    content = "Héllo wörld — 日本語テスト"
    state = _make_state(mime_type="text/plain", raw_content=content.encode("utf-8"))
    result = await extract_text(state)

    assert result["node_status"] == "skipped"
    assert result["extracted_text"] == content


@pytest.mark.anyio
async def test_skip_populates_skipped_nodes():
    """On skip, skipped_nodes should contain an entry for extract_text."""
    state = _make_state(mime_type="text/plain", raw_content=b"some text")
    result = await extract_text(state)

    assert len(result["skipped_nodes"]) == 1
    entry = result["skipped_nodes"][0]
    assert entry["node_name"] == "extract_text"
    assert entry["reason"] == "input_already_text"


@pytest.mark.anyio
async def test_skip_appends_to_completed_nodes():
    """On skip, 'extract_text' should be appended to completed_nodes."""
    state = _make_state(mime_type="text/plain", raw_content=b"data")
    result = await extract_text(state)

    assert "extract_text" in result["completed_nodes"]
    # Should preserve prior completed nodes
    assert "ingest" in result["completed_nodes"]


# --- Successful PDF Extraction Tests ---


@pytest.mark.anyio
async def test_successful_pdf_extraction():
    """PDF extraction with mocked extractor returns extracted text."""

    async def mock_pdf_extract(raw_content: bytes, timeout: int) -> str:
        return "Extracted PDF text content"

    state = _make_state(mime_type="application/pdf", raw_content=b"%PDF-1.4 fake")
    result = await extract_text(state, pdf_extractor=mock_pdf_extract)

    assert result["node_status"] == "completed"
    assert result["current_node"] == "extract_text"
    assert result["extracted_text"] == "Extracted PDF text content"
    assert result["error_type"] is None
    assert result["error_detail"] is None


@pytest.mark.anyio
async def test_pdf_extraction_appends_to_completed_nodes():
    """On successful PDF extraction, 'extract_text' in completed_nodes."""

    async def mock_pdf_extract(raw_content: bytes, timeout: int) -> str:
        return "text"

    state = _make_state(mime_type="application/pdf", raw_content=b"pdf bytes")
    result = await extract_text(state, pdf_extractor=mock_pdf_extract)

    assert "extract_text" in result["completed_nodes"]
    assert "ingest" in result["completed_nodes"]


# --- Successful DOCX Extraction Tests ---


@pytest.mark.anyio
async def test_successful_docx_extraction():
    """DOCX extraction with mocked extractor returns extracted text."""

    async def mock_docx_extract(raw_content: bytes, timeout: int) -> str:
        return "Extracted DOCX text content"

    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    state = _make_state(mime_type=mime, raw_content=b"PK\x03\x04 fake docx")
    result = await extract_text(state, docx_extractor=mock_docx_extract)

    assert result["node_status"] == "completed"
    assert result["current_node"] == "extract_text"
    assert result["extracted_text"] == "Extracted DOCX text content"
    assert result["error_type"] is None
    assert result["error_detail"] is None


@pytest.mark.anyio
async def test_docx_extraction_appends_to_completed_nodes():
    """On successful DOCX extraction, 'extract_text' in completed_nodes."""

    async def mock_docx_extract(raw_content: bytes, timeout: int) -> str:
        return "text"

    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    state = _make_state(mime_type=mime, raw_content=b"docx bytes")
    result = await extract_text(state, docx_extractor=mock_docx_extract)

    assert "extract_text" in result["completed_nodes"]


# --- Permanent Error Tests ---


@pytest.mark.anyio
async def test_permanent_error_on_corrupted_pdf():
    """Corrupted PDF (ValueError from extractor) should produce permanent error."""

    async def mock_pdf_corrupt(raw_content: bytes, timeout: int) -> str:
        raise ValueError("Unable to parse PDF structure")

    state = _make_state(mime_type="application/pdf", raw_content=b"corrupted data")
    result = await extract_text(state, pdf_extractor=mock_pdf_corrupt)

    assert result["node_status"] == "error"
    assert result["error_type"] == "permanent"
    assert "Corrupted file" in result["error_detail"]
    assert "Unable to parse PDF structure" in result["error_detail"]


@pytest.mark.anyio
async def test_permanent_error_on_corrupted_docx():
    """Corrupted DOCX (ValueError from extractor) should produce permanent error."""

    async def mock_docx_corrupt(raw_content: bytes, timeout: int) -> str:
        raise ValueError("Invalid DOCX archive")

    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    state = _make_state(mime_type=mime, raw_content=b"bad docx")
    result = await extract_text(state, docx_extractor=mock_docx_corrupt)

    assert result["node_status"] == "error"
    assert result["error_type"] == "permanent"
    assert "Corrupted file" in result["error_detail"]


@pytest.mark.anyio
async def test_permanent_error_does_not_append_to_completed_nodes():
    """On permanent error, 'extract_text' should NOT be in completed_nodes."""

    async def mock_pdf_corrupt(raw_content: bytes, timeout: int) -> str:
        raise ValueError("corrupted")

    state = _make_state(mime_type="application/pdf", raw_content=b"bad")
    result = await extract_text(state, pdf_extractor=mock_pdf_corrupt)

    assert "extract_text" not in result["completed_nodes"]


# --- Transient Error Tests ---


@pytest.mark.anyio
async def test_transient_error_on_timeout():
    """Timeout during extraction should produce transient error."""

    async def mock_pdf_timeout(raw_content: bytes, timeout: int) -> str:
        raise asyncio.TimeoutError()

    state = _make_state(mime_type="application/pdf", raw_content=b"pdf data")
    result = await extract_text(state, pdf_extractor=mock_pdf_timeout)

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert "timed out" in result["error_detail"]


@pytest.mark.anyio
async def test_transient_error_on_memory():
    """MemoryError during extraction should produce transient error."""

    async def mock_pdf_oom(raw_content: bytes, timeout: int) -> str:
        raise MemoryError()

    state = _make_state(mime_type="application/pdf", raw_content=b"big pdf")
    result = await extract_text(state, pdf_extractor=mock_pdf_oom)

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert "memory" in result["error_detail"]


@pytest.mark.anyio
async def test_transient_error_does_not_append_to_completed_nodes():
    """On transient error, 'extract_text' should NOT be in completed_nodes."""

    async def mock_pdf_timeout(raw_content: bytes, timeout: int) -> str:
        raise asyncio.TimeoutError()

    state = _make_state(mime_type="application/pdf", raw_content=b"data")
    result = await extract_text(state, pdf_extractor=mock_pdf_timeout)

    assert "extract_text" not in result["completed_nodes"]


# --- Edge Cases ---


@pytest.mark.anyio
async def test_skip_with_empty_raw_content():
    """Skip with None raw_content should produce empty extracted_text."""
    state = _make_state(mime_type="text/plain", raw_content=None)
    result = await extract_text(state)

    assert result["node_status"] == "skipped"
    assert result["extracted_text"] == ""


@pytest.mark.anyio
async def test_unsupported_mime_type_permanent_error():
    """Unsupported MIME type should produce permanent error."""
    state = _make_state(mime_type="image/png", raw_content=b"png data")
    result = await extract_text(state)

    assert result["node_status"] == "error"
    assert result["error_type"] == "permanent"
    assert "Unsupported MIME type" in result["error_detail"]
