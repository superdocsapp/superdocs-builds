"""Unit tests for pipeline state schema and factory function."""

import pytest

from src.pipeline.state import (
    ChunkEntry,
    ComplianceVerdict,
    Decision,
    ExtractionResult,
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    SkippedNodeEntry,
    create_initial_state,
)


@pytest.fixture
def default_config() -> PipelineConfig:
    """A valid default PipelineConfig."""
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


class TestCreateInitialState:
    """Tests for the create_initial_state factory function."""

    def test_returns_pipeline_state_with_identity_fields(self, default_config: PipelineConfig):
        state = create_initial_state(
            run_id="abc-123",
            document_id="doc-456",
            document_version_id="ver-789",
            config=default_config,
        )
        assert state["run_id"] == "abc-123"
        assert state["document_id"] == "doc-456"
        assert state["document_version_id"] == "ver-789"

    def test_execution_tracking_defaults(self, default_config: PipelineConfig):
        state = create_initial_state("r", "d", "v", default_config)
        assert state["current_node"] == ""
        assert state["node_status"] == "completed"
        assert state["error_type"] is None
        assert state["error_detail"] is None
        assert state["retries"] == {}
        assert state["skipped_nodes"] == []
        assert state["completed_nodes"] == []

    def test_config_is_preserved(self, default_config: PipelineConfig):
        state = create_initial_state("r", "d", "v", default_config)
        assert state["config"] == default_config
        assert state["config"]["max_retries"] == 3
        assert state["config"]["chunk_max_size"] == 1000
        assert state["config"]["confidence_threshold"] == 0.7

    def test_understand_stage_defaults(self, default_config: PipelineConfig):
        state = create_initial_state("r", "d", "v", default_config)
        assert state["raw_content"] is None
        assert state["mime_type"] is None
        assert state["extracted_text"] is None
        assert state["chunks"] == []
        assert state["embeddings_stored"] is False

    def test_examine_stage_defaults(self, default_config: PipelineConfig):
        state = create_initial_state("r", "d", "v", default_config)
        assert state["claims"] == []
        assert state["verdicts"] == []

    def test_stay_alive_stage_defaults(self, default_config: PipelineConfig):
        state = create_initial_state("r", "d", "v", default_config)
        assert state["queue_buckets"] == {
            "auto_approve": [],
            "escalate": [],
            "auto_reject": [],
        }
        assert state["decisions"] == []

    def test_all_pipeline_state_keys_present(self, default_config: PipelineConfig):
        state = create_initial_state("r", "d", "v", default_config)
        expected_keys = {
            "run_id",
            "document_id",
            "document_version_id",
            "current_node",
            "node_status",
            "error_type",
            "error_detail",
            "retries",
            "skipped_nodes",
            "completed_nodes",
            "config",
            "raw_content",
            "mime_type",
            "extracted_text",
            "chunks",
            "embeddings_stored",
            "classification_label",
            "classification_confidence",
            "classification_scores",
            "claims",
            "verdicts",
            "playbook_id",
            "source_rules",
            "claims_rules",
            "findings",
            "claim_findings",
            "source_findings",
            "queue_buckets",
            "decisions",
            "_last_node_metrics",
            "_persistence_gap",
        }
        assert set(state.keys()) == expected_keys

    def test_classification_defaults(self, default_config: PipelineConfig):
        state = create_initial_state("r", "d", "v", default_config)
        assert state["classification_label"] is None
        assert state["classification_confidence"] is None
        assert state["classification_scores"] is None


class TestTypedDictStructures:
    """Tests verifying TypedDict structures can be instantiated correctly."""

    def test_chunk_entry(self):
        chunk = ChunkEntry(index=0, text="hello world", start_offset=0, end_offset=11)
        assert chunk["index"] == 0
        assert chunk["text"] == "hello world"
        assert chunk["start_offset"] == 0
        assert chunk["end_offset"] == 11

    def test_extraction_result(self):
        result = ExtractionResult(
            claim_id="claim-1",
            claim_text="The interest rate is 5%",
            chunk_index=0,
            start_offset=0,
            end_offset=23,
            confidence=0.95,
        )
        assert result["claim_id"] == "claim-1"
        assert result["confidence"] == 0.95

    def test_compliance_verdict(self):
        verdict = ComplianceVerdict(
            claim_id="claim-1",
            verdict="compliant",
            confidence=0.85,
            needs_human_review=False,
            rule_id="rule-a",
            evidence_refs=["ref-1", "ref-2"],
        )
        assert verdict["verdict"] == "compliant"
        assert verdict["needs_human_review"] is False
        assert len(verdict["evidence_refs"]) == 2

    def test_decision(self):
        decision = Decision(
            claim_id="claim-1",
            approval_queue_id="queue-1",
            decision_value="approved",
            reviewer_id="user-42",
            justification="Meets all requirements",
        )
        assert decision["decision_value"] == "approved"
        assert decision["reviewer_id"] == "user-42"

    def test_skipped_node_entry(self):
        entry = SkippedNodeEntry(node_name="extract_text", reason="input_already_text")
        assert entry["node_name"] == "extract_text"
        assert entry["reason"] == "input_already_text"

    def test_queue_buckets(self):
        buckets = QueueBuckets(
            auto_approve=["c1", "c2"],
            escalate=["c3"],
            auto_reject=[],
        )
        assert len(buckets["auto_approve"]) == 2
        assert buckets["escalate"] == ["c3"]
        assert buckets["auto_reject"] == []
