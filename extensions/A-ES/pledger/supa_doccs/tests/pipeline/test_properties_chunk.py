"""Property-based tests for chunk node coverage.

**Validates: Requirements 8.3**

Property 11: Chunk Coverage
For any non-empty text and valid (chunk_max_size, chunk_overlap) parameters where
chunk_max_size > chunk_overlap > 0, when the chunk node processes the text, the
union of all chunk character ranges [start_offset, end_offset) covers every
character position 0..len(text)-1 with no gaps.
"""

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.nodes.chunk import chunk
from src.pipeline.state import (
    PipelineConfig,
    PipelineState,
    QueueBuckets,
)


# --- Strategies ---


@st.composite
def chunk_params(draw: st.DrawFn) -> tuple[str, int, int]:
    """Generate non-empty text and valid chunk_max_size/chunk_overlap parameters.

    Returns:
        Tuple of (text, chunk_max_size, chunk_overlap) where
        chunk_max_size > chunk_overlap > 0.
    """
    text = draw(st.text(min_size=1, max_size=5000))
    chunk_overlap = draw(st.integers(min_value=1, max_value=500))
    chunk_max_size = draw(st.integers(min_value=chunk_overlap + 1, max_value=chunk_overlap + 5000))
    return text, chunk_max_size, chunk_overlap


def _make_state(text: str, chunk_max_size: int, chunk_overlap: int) -> PipelineState:
    """Create a minimal PipelineState for chunk node testing."""
    config = PipelineConfig(
        max_retries=3,
        chunk_max_size=chunk_max_size,
        chunk_overlap=chunk_overlap,
        confidence_threshold=0.7,
        review_timeout_hours=72,
        reminder_interval_hours=24,
        poll_interval_seconds=30,
        extract_text_timeout_seconds=60,
        min_chunk_threshold=1,  # Always run chunking for non-empty text
    )
    return PipelineState(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        current_node="extract_text",
        node_status="completed",
        error_type=None,
        error_detail=None,
        retries={},
        skipped_nodes=[],
        completed_nodes=["ingest", "extract_text"],
        config=config,
        raw_content=None,
        mime_type="text/plain",
        extracted_text=text,
        chunks=[],
        embeddings_stored=False,
        claims=[],
        verdicts=[],
        queue_buckets=QueueBuckets(
            auto_approve=[],
            escalate=[],
            auto_reject=[],
        ),
        decisions=[],
    )


# --- Property Test ---


@given(params=chunk_params())
@settings(max_examples=200)
def test_chunk_coverage_no_gaps(params: tuple[str, int, int]) -> None:
    """Property 11: Chunk Coverage.

    **Validates: Requirements 8.3**

    For any non-empty text and valid (chunk_max_size, chunk_overlap) parameters,
    the union of all chunk character ranges covers every character position in
    the original text with no gaps.
    """
    text, chunk_max_size, chunk_overlap = params
    state = _make_state(text, chunk_max_size, chunk_overlap)

    result = asyncio.run(chunk(state))

    # The node should complete successfully (completed or skipped)
    assert result["node_status"] in ("completed", "skipped"), (
        f"Expected completed/skipped but got {result['node_status']}: "
        f"{result.get('error_detail')}"
    )

    chunks = result["chunks"]
    assert len(chunks) > 0, "Expected at least one chunk for non-empty text"

    text_length = len(text)

    # Collect all covered positions using chunk ranges
    covered = set()
    for c in chunks:
        for pos in range(c["start_offset"], c["end_offset"]):
            covered.add(pos)

    # Assert every character position is covered
    expected_positions = set(range(text_length))
    missing = expected_positions - covered
    assert len(missing) == 0, (
        f"Positions not covered by any chunk: {sorted(missing)[:20]}... "
        f"(total missing: {len(missing)} of {text_length})"
    )

    # Assert no gap between consecutive chunk start positions
    # (each chunk's start should be reachable from the previous chunk's range)
    if len(chunks) > 1:
        sorted_chunks = sorted(chunks, key=lambda c: c["start_offset"])
        for i in range(1, len(sorted_chunks)):
            prev_end = sorted_chunks[i - 1]["end_offset"]
            curr_start = sorted_chunks[i]["start_offset"]
            assert curr_start <= prev_end, (
                f"Gap between chunk {i-1} (end={prev_end}) and "
                f"chunk {i} (start={curr_start})"
            )
