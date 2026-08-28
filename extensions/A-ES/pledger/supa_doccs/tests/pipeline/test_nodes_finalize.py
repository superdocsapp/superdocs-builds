"""Unit tests for the finalize node.

Tests cover:
- Successful finalization with all buckets and decisions
- Successful finalization without human review (no decisions)
- Transient error on DB failure
- completed_nodes includes "finalize" on success
- completed_nodes does NOT include "finalize" on error
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.nodes.finalize import (
    FinalizeWriter,
    finalize,
    set_writer,
)
from src.pipeline.state import (
    Decision,
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


# --- Mock Writer ---


class MockFinalizeWriter:
    """A mock FinalizeWriter that records calls for assertion."""

    def __init__(self, should_raise: Exception | None = None):
        self.calls: list[dict] = []
        self.should_raise = should_raise

    async def finalize_run(
        self,
        run_id: str,
        auto_approve_ids: list[str],
        auto_reject_ids: list[str],
        approved_ids: list[str],
        rejected_ids: list[str],
    ) -> None:
        self.calls.append(
            {
                "run_id": run_id,
                "auto_approve_ids": auto_approve_ids,
                "auto_reject_ids": auto_reject_ids,
                "approved_ids": approved_ids,
                "rejected_ids": rejected_ids,
            }
        )
        if self.should_raise:
            raise self.should_raise


# --- Fixtures ---


@pytest.fixture
def base_state() -> PipelineState:
    """Create a pipeline state ready for finalize."""
    config = load_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=config,
    )
    # Simulate previous nodes having completed
    state["completed_nodes"] = [
        "ingest",
        "extract_text",
        "chunk",
        "embed",
        "extract_claims",
        "match_rules",
        "score_confidence",
        "route_to_queue",
        "human_review",
    ]
    return state


@pytest.fixture(autouse=True)
def reset_writer():
    """Reset the module-level writer before each test."""
    set_writer(None)
    yield
    set_writer(None)


# --- Tests ---


@pytest.mark.anyio
async def test_successful_finalization_with_all_buckets_and_decisions(
    base_state: PipelineState,
):
    """Finalize succeeds with auto_approve, auto_reject, and human decisions."""
    writer = MockFinalizeWriter()
    set_writer(writer)

    base_state["queue_buckets"] = QueueBuckets(
        auto_approve=["c1", "c2"],
        escalate=["c3", "c4"],
        auto_reject=["c5"],
    )
    base_state["decisions"] = [
        Decision(
            claim_id="c3",
            approval_queue_id="aq-1",
            decision_value="approved",
            reviewer_id="reviewer-1",
            justification="Looks good",
        ),
        Decision(
            claim_id="c4",
            approval_queue_id="aq-2",
            decision_value="rejected",
            reviewer_id="reviewer-2",
            justification="Does not meet criteria",
        ),
    ]

    result = await finalize(base_state)

    assert result["node_status"] == "completed"
    assert result["current_node"] == "finalize"
    assert result["error_type"] is None
    assert result["error_detail"] is None

    # Verify writer was called with correct arguments
    assert len(writer.calls) == 1
    call = writer.calls[0]
    assert call["run_id"] == "test-run-id"
    assert call["auto_approve_ids"] == ["c1", "c2"]
    assert call["auto_reject_ids"] == ["c5"]
    assert call["approved_ids"] == ["c3"]
    assert call["rejected_ids"] == ["c4"]


@pytest.mark.anyio
async def test_successful_finalization_without_human_review(
    base_state: PipelineState,
):
    """Finalize succeeds when human review was skipped (no decisions)."""
    writer = MockFinalizeWriter()
    set_writer(writer)

    base_state["queue_buckets"] = QueueBuckets(
        auto_approve=["c1", "c2", "c3"],
        escalate=[],
        auto_reject=["c4"],
    )
    base_state["decisions"] = []

    result = await finalize(base_state)

    assert result["node_status"] == "completed"
    assert result["current_node"] == "finalize"
    assert result["error_type"] is None
    assert result["error_detail"] is None

    # Verify writer was called with empty human decisions
    assert len(writer.calls) == 1
    call = writer.calls[0]
    assert call["run_id"] == "test-run-id"
    assert call["auto_approve_ids"] == ["c1", "c2", "c3"]
    assert call["auto_reject_ids"] == ["c4"]
    assert call["approved_ids"] == []
    assert call["rejected_ids"] == []


@pytest.mark.anyio
async def test_transient_error_on_db_failure(base_state: PipelineState):
    """Finalize returns transient error when DB transaction fails."""
    writer = MockFinalizeWriter(
        should_raise=RuntimeError("Connection lost")
    )
    set_writer(writer)

    base_state["queue_buckets"] = QueueBuckets(
        auto_approve=["c1"],
        escalate=[],
        auto_reject=[],
    )
    base_state["decisions"] = []

    result = await finalize(base_state)

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert "DB transaction failure" in result["error_detail"]
    assert "Connection lost" in result["error_detail"]
    assert result["current_node"] == "finalize"


@pytest.mark.anyio
async def test_completed_nodes_includes_finalize_on_success(
    base_state: PipelineState,
):
    """completed_nodes should include 'finalize' on successful finalization."""
    writer = MockFinalizeWriter()
    set_writer(writer)

    base_state["queue_buckets"] = QueueBuckets(
        auto_approve=["c1"],
        escalate=[],
        auto_reject=[],
    )
    base_state["decisions"] = []
    base_state["completed_nodes"] = ["ingest", "extract_text", "chunk"]

    result = await finalize(base_state)

    assert result["node_status"] == "completed"
    assert "finalize" in result["completed_nodes"]
    assert result["completed_nodes"] == [
        "ingest",
        "extract_text",
        "chunk",
        "finalize",
    ]


@pytest.mark.anyio
async def test_completed_nodes_does_not_include_finalize_on_error(
    base_state: PipelineState,
):
    """completed_nodes should NOT include 'finalize' on error."""
    writer = MockFinalizeWriter(
        should_raise=RuntimeError("Transaction timeout")
    )
    set_writer(writer)

    base_state["queue_buckets"] = QueueBuckets(
        auto_approve=["c1"],
        escalate=[],
        auto_reject=[],
    )
    base_state["decisions"] = []
    base_state["completed_nodes"] = ["ingest", "extract_text", "chunk"]

    result = await finalize(base_state)

    assert result["node_status"] == "error"
    assert "finalize" not in result["completed_nodes"]
    assert result["completed_nodes"] == ["ingest", "extract_text", "chunk"]


@pytest.mark.anyio
async def test_transient_error_when_writer_not_configured(
    base_state: PipelineState,
):
    """Finalize returns transient error if no FinalizeWriter is configured."""
    # Writer is None (reset by autouse fixture)
    base_state["queue_buckets"] = QueueBuckets(
        auto_approve=["c1"],
        escalate=[],
        auto_reject=[],
    )
    base_state["decisions"] = []

    result = await finalize(base_state)

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert "not configured" in result["error_detail"]
    assert "finalize" not in result["completed_nodes"]
