"""Property-based tests for PipelineState JSONB round-trip serialization.

**Validates: Requirements 7.5, 6.2**

Property 6: State JSONB Round-Trip
For any valid PipelineState, deserialize_state(serialize_state(state)) == state.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.serialization import deserialize_state, serialize_state
from src.pipeline.state import (
    ChunkEntry,
    ComplianceVerdict,
    Decision,
    ExtractionResult,
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    SkippedNodeEntry,
)


# --- Strategies ---

ALLOWED_MIME_TYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
]

NODE_NAMES = [
    "ingest",
    "extract_text",
    "chunk",
    "embed",
    "extract_claims",
    "match_rules",
    "score_confidence",
    "route_to_queue",
    "human_review",
    "finalize",
]


@st.composite
def pipeline_configs(draw: st.DrawFn) -> PipelineConfig:
    """Generate valid PipelineConfig instances respecting constraints."""
    chunk_overlap = draw(st.integers(min_value=1, max_value=500))
    chunk_max_size = draw(st.integers(min_value=chunk_overlap + 1, max_value=5000))

    return PipelineConfig(
        max_retries=draw(st.integers(min_value=0, max_value=10)),
        chunk_max_size=chunk_max_size,
        chunk_overlap=chunk_overlap,
        confidence_threshold=draw(st.floats(min_value=0.0, max_value=1.0)),
        review_timeout_hours=draw(st.integers(min_value=1, max_value=168)),
        reminder_interval_hours=draw(st.integers(min_value=1, max_value=72)),
        poll_interval_seconds=draw(st.integers(min_value=1, max_value=300)),
        extract_text_timeout_seconds=draw(st.integers(min_value=1, max_value=600)),
        min_chunk_threshold=draw(st.integers(min_value=1, max_value=1000)),
    )


@st.composite
def chunk_entries(draw: st.DrawFn) -> ChunkEntry:
    """Generate valid ChunkEntry instances with consistent offsets."""
    start = draw(st.integers(min_value=0, max_value=10000))
    length = draw(st.integers(min_value=1, max_value=1000))
    text = draw(st.text(min_size=1, max_size=100))
    return ChunkEntry(
        index=draw(st.integers(min_value=0, max_value=100)),
        text=text,
        start_offset=start,
        end_offset=start + length,
    )


@st.composite
def extraction_results(draw: st.DrawFn) -> ExtractionResult:
    """Generate valid ExtractionResult instances."""
    start = draw(st.integers(min_value=0, max_value=10000))
    end = draw(st.integers(min_value=start + 1, max_value=start + 1000))
    return ExtractionResult(
        claim_id=draw(st.uuids().map(str)),
        claim_text=draw(st.text(min_size=1, max_size=200)),
        chunk_index=draw(st.integers(min_value=0, max_value=50)),
        start_offset=start,
        end_offset=end,
        confidence=draw(st.floats(min_value=0.0, max_value=1.0)),
    )


@st.composite
def compliance_verdicts(draw: st.DrawFn) -> ComplianceVerdict:
    """Generate valid ComplianceVerdict instances."""
    return ComplianceVerdict(
        claim_id=draw(st.uuids().map(str)),
        verdict=draw(st.sampled_from(["compliant", "non_compliant", "indeterminate"])),
        confidence=draw(st.floats(min_value=0.0, max_value=1.0)),
        needs_human_review=draw(st.booleans()),
        rule_id=draw(st.none() | st.text(min_size=1, max_size=50)),
        evidence_refs=draw(st.lists(st.text(min_size=1, max_size=50), max_size=5)),
    )


@st.composite
def decisions(draw: st.DrawFn) -> Decision:
    """Generate valid Decision instances."""
    return Decision(
        claim_id=draw(st.uuids().map(str)),
        approval_queue_id=draw(st.uuids().map(str)),
        decision_value=draw(st.sampled_from(["approved", "rejected"])),
        reviewer_id=draw(st.uuids().map(str)),
        justification=draw(st.text(min_size=1, max_size=200)),
    )


@st.composite
def skipped_node_entries(draw: st.DrawFn) -> SkippedNodeEntry:
    """Generate valid SkippedNodeEntry instances."""
    return SkippedNodeEntry(
        node_name=draw(st.sampled_from(NODE_NAMES)),
        reason=draw(st.text(min_size=1, max_size=255)),
    )


@st.composite
def queue_buckets(draw: st.DrawFn) -> QueueBuckets:
    """Generate valid QueueBuckets with lists of claim ID strings."""
    return QueueBuckets(
        auto_approve=draw(st.lists(st.uuids().map(str), max_size=5)),
        escalate=draw(st.lists(st.uuids().map(str), max_size=5)),
        auto_reject=draw(st.lists(st.uuids().map(str), max_size=5)),
    )


@st.composite
def pipeline_states(draw: st.DrawFn) -> PipelineState:
    """Generate valid PipelineState instances with all fields populated."""
    return PipelineState(
        # Identity
        run_id=draw(st.uuids().map(str)),
        document_id=draw(st.uuids().map(str)),
        document_version_id=draw(st.uuids().map(str)),
        # Execution tracking
        current_node=draw(st.sampled_from(NODE_NAMES + [""])),
        node_status=draw(st.sampled_from(["completed", "skipped", "error"])),
        error_type=draw(st.none() | st.sampled_from(["transient", "permanent"])),
        error_detail=draw(st.none() | st.text(min_size=1, max_size=200)),
        retries=draw(
            st.dictionaries(
                keys=st.sampled_from(NODE_NAMES),
                values=st.integers(min_value=0, max_value=10),
                max_size=5,
            )
        ),
        skipped_nodes=draw(st.lists(skipped_node_entries(), max_size=3)),
        completed_nodes=draw(st.lists(st.sampled_from(NODE_NAMES), max_size=10)),
        # Configuration
        config=draw(pipeline_configs()),
        # Understand Stage outputs
        raw_content=draw(st.none() | st.binary(min_size=0, max_size=500)),
        mime_type=draw(st.none() | st.sampled_from(ALLOWED_MIME_TYPES)),
        extracted_text=draw(st.none() | st.text(min_size=0, max_size=500)),
        chunks=draw(st.lists(chunk_entries(), max_size=5)),
        embeddings_stored=draw(st.booleans()),
        # Examine Stage outputs
        claims=draw(st.lists(extraction_results(), max_size=5)),
        verdicts=draw(st.lists(compliance_verdicts(), max_size=5)),
        # Stay-Alive Stage outputs
        queue_buckets=draw(queue_buckets()),
        decisions=draw(st.lists(decisions(), max_size=5)),
    )


# --- Property Test ---


@given(state=pipeline_states())
@settings(max_examples=200)
def test_state_jsonb_round_trip(state: PipelineState) -> None:
    """Property 6: State JSONB Round-Trip.

    **Validates: Requirements 7.5, 6.2**

    For any valid PipelineState, serializing to JSONB-compatible dict and
    deserializing back must produce the original state unchanged.
    """
    serialized = serialize_state(state)
    deserialized = deserialize_state(serialized)
    assert deserialized == state
