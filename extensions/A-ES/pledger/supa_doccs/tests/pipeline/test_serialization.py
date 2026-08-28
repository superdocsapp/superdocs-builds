"""Unit tests for PipelineState JSONB serialization/deserialization."""

import base64

from src.pipeline.serialization import deserialize_state, serialize_state
from src.pipeline.state import (
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


def _make_config() -> PipelineConfig:
    return PipelineConfig(
        max_retries=3,
        chunk_max_size=1000,
        chunk_overlap=200,
        confidence_threshold=0.7,
        review_timeout_hours=72,
        reminder_interval_hours=24,
        poll_interval_seconds=30,
        extract_text_timeout_seconds=60,
        min_chunk_threshold=200,
    )


def _make_full_state(raw_content: bytes | None = None) -> PipelineState:
    """Create a PipelineState with representative data in all fields."""
    return PipelineState(
        run_id="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        document_id="11112222333344445555666677778888",
        document_version_id="aaaabbbbccccddddeeeeffffaaaabbbb",
        current_node="extract_text",
        node_status="completed",
        error_type=None,
        error_detail=None,
        retries={"ingest": 0, "extract_text": 1},
        skipped_nodes=[{"node_name": "chunk", "reason": "input_already_text"}],
        completed_nodes=["ingest", "extract_text"],
        config=_make_config(),
        raw_content=raw_content,
        mime_type="application/pdf",
        extracted_text="Hello world. This is a test document.",
        chunks=[
            {
                "index": 0,
                "text": "Hello world.",
                "start_offset": 0,
                "end_offset": 12,
            },
            {
                "index": 1,
                "text": "This is a test document.",
                "start_offset": 13,
                "end_offset": 37,
            },
        ],
        embeddings_stored=True,
        claims=[
            {
                "claim_id": "claim-001",
                "claim_text": "Interest rate is 5%",
                "chunk_index": 0,
                "start_offset": 0,
                "end_offset": 19,
                "confidence": 0.92,
            }
        ],
        verdicts=[
            {
                "claim_id": "claim-001",
                "verdict": "compliant",
                "confidence": 0.92,
                "needs_human_review": False,
                "rule_id": "rule-42",
                "evidence_refs": ["chunk-0"],
            }
        ],
        queue_buckets=QueueBuckets(
            auto_approve=["claim-001"],
            escalate=[],
            auto_reject=[],
        ),
        decisions=[
            {
                "claim_id": "claim-001",
                "approval_queue_id": "aq-123",
                "decision_value": "approved",
                "reviewer_id": "reviewer-abc",
                "justification": "Looks good",
            }
        ],
    )


class TestSerializeStateWithNoneRawContent:
    """Test round-trip when raw_content is None."""

    def test_round_trip_none_raw_content(self):
        state = _make_full_state(raw_content=None)
        serialized = serialize_state(state)
        deserialized = deserialize_state(serialized)
        assert deserialized == state

    def test_serialized_raw_content_is_none(self):
        state = _make_full_state(raw_content=None)
        serialized = serialize_state(state)
        assert serialized["raw_content"] is None


class TestSerializeStateWithBytesRawContent:
    """Test round-trip when raw_content is bytes."""

    def test_round_trip_bytes_raw_content(self):
        content = b"PDF binary content \x00\x01\x02\xff"
        state = _make_full_state(raw_content=content)
        serialized = serialize_state(state)
        deserialized = deserialize_state(serialized)
        assert deserialized == state

    def test_serialized_raw_content_is_base64_string(self):
        content = b"Hello PDF"
        state = _make_full_state(raw_content=content)
        serialized = serialize_state(state)
        assert isinstance(serialized["raw_content"], str)
        # Verify it's valid base64 that decodes back
        assert base64.b64decode(serialized["raw_content"]) == content

    def test_round_trip_empty_bytes(self):
        state = _make_full_state(raw_content=b"")
        serialized = serialize_state(state)
        deserialized = deserialize_state(serialized)
        assert deserialized == state
        assert deserialized["raw_content"] == b""


class TestNestedTypesPreserved:
    """Test that all nested types survive the round-trip correctly."""

    def test_config_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["config"] == state["config"]

    def test_chunks_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["chunks"] == state["chunks"]

    def test_claims_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["claims"] == state["claims"]

    def test_verdicts_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["verdicts"] == state["verdicts"]

    def test_queue_buckets_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["queue_buckets"] == state["queue_buckets"]

    def test_decisions_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["decisions"] == state["decisions"]

    def test_retries_dict_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["retries"] == state["retries"]

    def test_skipped_nodes_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["skipped_nodes"] == state["skipped_nodes"]

    def test_completed_nodes_preserved(self):
        state = _make_full_state()
        result = deserialize_state(serialize_state(state))
        assert result["completed_nodes"] == state["completed_nodes"]


class TestInitialStateRoundTrip:
    """Test round-trip with a freshly created initial state."""

    def test_round_trip_initial_state(self):
        state = create_initial_state(
            run_id="deadbeef" * 4,
            document_id="cafebabe" * 4,
            document_version_id="12345678" * 4,
            config=_make_config(),
        )
        serialized = serialize_state(state)
        deserialized = deserialize_state(serialized)
        assert deserialized == state
