"""Unit tests for the chunk node."""

import pytest

from src.pipeline.nodes.chunk import chunk
from src.pipeline.state import (
    ChunkEntry,
    PipelineState,
    PipelineConfig,
    QueueBuckets,
    create_initial_state,
)


def _make_config(
    chunk_max_size: int = 1000,
    chunk_overlap: int = 200,
    min_chunk_threshold: int = 200,
) -> PipelineConfig:
    """Create a PipelineConfig with custom chunking params."""
    return PipelineConfig(
        max_retries=3,
        chunk_max_size=chunk_max_size,
        chunk_overlap=chunk_overlap,
        confidence_threshold=0.7,
        review_timeout_hours=72,
        reminder_interval_hours=24,
        poll_interval_seconds=30,
        extract_text_timeout_seconds=60,
        min_chunk_threshold=min_chunk_threshold,
    )


def _make_state(
    extracted_text: str | None = None,
    config: PipelineConfig | None = None,
) -> PipelineState:
    """Create an initial pipeline state with the given extracted_text."""
    if config is None:
        config = _make_config()
    state = create_initial_state(
        run_id="run-001",
        document_id="doc-001",
        document_version_id="ver-001",
        config=config,
    )
    state["extracted_text"] = extracted_text  # type: ignore[typeddict-item]
    return state


@pytest.mark.anyio
async def test_normal_chunking_with_overlap():
    """Normal chunking produces correct overlapping chunks."""
    # chunk_max_size=10, overlap=3, stride=7
    # text = "abcdefghijklmnopqrstuvwxyz" (26 chars)
    # chunk 0: [0:10] = "abcdefghij"
    # chunk 1: [7:17] = "hijklmnopq"
    # chunk 2: [14:24] = "opqrstuvwx"
    # chunk 3: [21:26] = "uvwxy z" -> "uvwxyz"
    config = _make_config(chunk_max_size=10, chunk_overlap=3, min_chunk_threshold=5)
    text = "abcdefghijklmnopqrstuvwxyz"
    state = _make_state(extracted_text=text, config=config)

    result = await chunk(state)

    assert result["node_status"] == "completed"
    assert result["current_node"] == "chunk"
    assert result["error_type"] is None
    assert result["error_detail"] is None

    chunks = result["chunks"]
    assert len(chunks) == 4

    assert chunks[0] == ChunkEntry(index=0, text="abcdefghij", start_offset=0, end_offset=10)
    assert chunks[1] == ChunkEntry(index=1, text="hijklmnopq", start_offset=7, end_offset=17)
    assert chunks[2] == ChunkEntry(index=2, text="opqrstuvwx", start_offset=14, end_offset=24)
    assert chunks[3] == ChunkEntry(index=3, text="vwxyz", start_offset=21, end_offset=26)


@pytest.mark.anyio
async def test_skip_when_text_below_min_chunk_threshold():
    """When text is shorter than min_chunk_threshold, node is skipped but produces a single chunk."""
    config = _make_config(min_chunk_threshold=200)
    text = "short text"  # 10 chars, well below 200
    state = _make_state(extracted_text=text, config=config)

    result = await chunk(state)

    assert result["node_status"] == "skipped"
    assert result["current_node"] == "chunk"
    assert result["error_type"] is None
    assert result["error_detail"] is None

    # Still produces a single chunk
    chunks = result["chunks"]
    assert len(chunks) == 1
    assert chunks[0] == ChunkEntry(index=0, text="short text", start_offset=0, end_offset=10)

    # skipped_nodes is populated
    skipped = result["skipped_nodes"]
    assert any(
        entry["node_name"] == "chunk" and entry["reason"] == "below_chunk_threshold"
        for entry in skipped
    )

    # completed_nodes contains chunk (skipped nodes still get appended)
    assert "chunk" in result["completed_nodes"]


@pytest.mark.anyio
async def test_permanent_error_on_none_extracted_text():
    """Permanent error when extracted_text is None."""
    state = _make_state(extracted_text=None)

    result = await chunk(state)

    assert result["node_status"] == "error"
    assert result["current_node"] == "chunk"
    assert result["error_type"] == "permanent"
    assert result["error_detail"] == "extracted_text is None or empty"
    # completed_nodes should NOT include chunk
    assert "chunk" not in result["completed_nodes"]


@pytest.mark.anyio
async def test_permanent_error_on_empty_string_extracted_text():
    """Permanent error when extracted_text is empty string."""
    state = _make_state(extracted_text="")

    result = await chunk(state)

    assert result["node_status"] == "error"
    assert result["current_node"] == "chunk"
    assert result["error_type"] == "permanent"
    assert result["error_detail"] == "extracted_text is None or empty"
    # completed_nodes should NOT include chunk
    assert "chunk" not in result["completed_nodes"]


@pytest.mark.anyio
async def test_chunk_offsets_cover_full_text_no_gaps():
    """All characters in the original text are covered by chunks with no gaps."""
    config = _make_config(chunk_max_size=15, chunk_overlap=5, min_chunk_threshold=5)
    text = "The quick brown fox jumps over the lazy dog"  # 43 chars
    state = _make_state(extracted_text=text, config=config)

    result = await chunk(state)

    assert result["node_status"] == "completed"
    chunks = result["chunks"]

    # Verify no gaps: every character position is covered
    covered = set()
    for c in chunks:
        for i in range(c["start_offset"], c["end_offset"]):
            covered.add(i)

    expected = set(range(len(text)))
    assert covered == expected, f"Missing positions: {expected - covered}"

    # Verify chunks are ordered and contiguous coverage
    for i, c in enumerate(chunks):
        assert c["index"] == i
        # Each chunk's text matches the substring
        assert c["text"] == text[c["start_offset"]:c["end_offset"]]


@pytest.mark.anyio
async def test_completed_nodes_populated_on_success():
    """completed_nodes is updated when chunk completes successfully."""
    config = _make_config(chunk_max_size=100, chunk_overlap=10, min_chunk_threshold=5)
    text = "a" * 250  # above threshold, will be chunked normally
    state = _make_state(extracted_text=text, config=config)

    result = await chunk(state)

    assert result["node_status"] == "completed"
    assert "chunk" in result["completed_nodes"]


@pytest.mark.anyio
async def test_skipped_nodes_populated_on_skip():
    """skipped_nodes is updated when chunk is skipped."""
    config = _make_config(min_chunk_threshold=200)
    text = "tiny"  # 4 chars, below threshold
    state = _make_state(extracted_text=text, config=config)

    result = await chunk(state)

    assert result["node_status"] == "skipped"
    assert "chunk" in result["completed_nodes"]
    assert any(
        entry["node_name"] == "chunk" and entry["reason"] == "below_chunk_threshold"
        for entry in result["skipped_nodes"]
    )


@pytest.mark.anyio
async def test_single_chunk_when_text_fits_in_one():
    """When text is longer than threshold but fits in one chunk_max_size, produces single chunk."""
    config = _make_config(chunk_max_size=100, chunk_overlap=20, min_chunk_threshold=5)
    text = "hello world"  # 11 chars, above threshold(5), but below chunk_max_size(100)
    state = _make_state(extracted_text=text, config=config)

    result = await chunk(state)

    assert result["node_status"] == "completed"
    chunks = result["chunks"]
    assert len(chunks) == 1
    assert chunks[0] == ChunkEntry(index=0, text="hello world", start_offset=0, end_offset=11)
