"""Unit tests for the human_review interrupt node.

Tests cover:
- Successful insertion and decision reading
- completed_nodes includes "human_review" on success
- Decisions are properly populated in state
- interrupt() is called during execution
- Error handling for queue writer failures
- Error handling for decision reader failures
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.nodes.human_review import (
    ApprovalQueueWriter,
    DecisionReader,
    InterruptHandler,
    human_review,
)
from src.pipeline.state import (
    Decision,
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


# --- Mock Implementations ---


class MockApprovalQueueWriter:
    """Mock queue writer that records calls."""

    def __init__(self) -> None:
        self.inserted: list[tuple[list[str], str]] = []

    async def insert_pending(self, claim_ids: list[str], run_id: str) -> None:
        self.inserted.append((claim_ids, run_id))


class MockDecisionReader:
    """Mock decision reader that returns preconfigured decisions."""

    def __init__(self, decisions: list[Decision]) -> None:
        self._decisions = decisions

    async def read_decisions(self, run_id: str) -> list[Decision]:
        return self._decisions


class MockInterruptHandler:
    """Mock interrupt handler that tracks calls."""

    def __init__(self) -> None:
        self.call_count = 0

    def interrupt(self) -> None:
        self.call_count += 1


class FailingQueueWriter:
    """Queue writer that raises an exception."""

    async def insert_pending(self, claim_ids: list[str], run_id: str) -> None:
        raise RuntimeError("Database connection failed")


class FailingDecisionReader:
    """Decision reader that raises an exception."""

    async def read_decisions(self, run_id: str) -> list[Decision]:
        raise RuntimeError("Decision table unreachable")


# --- Fixtures ---


@pytest.fixture
def base_state() -> PipelineState:
    """Create a pipeline state ready for human_review with escalated claims."""
    config = load_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=config,
    )
    state["queue_buckets"] = QueueBuckets(
        auto_approve=["c1", "c2"],
        escalate=["c3", "c4", "c5"],
        auto_reject=[],
    )
    state["completed_nodes"] = ["ingest", "extract_text", "chunk", "route_to_queue"]
    return state


@pytest.fixture
def sample_decisions() -> list[Decision]:
    """Return sample decisions for escalated claims."""
    return [
        Decision(
            claim_id="c3",
            approval_queue_id="aq-1",
            decision_value="approved",
            reviewer_id="reviewer-a",
            justification="Claim verified against source document",
        ),
        Decision(
            claim_id="c4",
            approval_queue_id="aq-2",
            decision_value="rejected",
            reviewer_id="reviewer-b",
            justification="Claim contradicts regulatory guidelines",
        ),
        Decision(
            claim_id="c5",
            approval_queue_id="aq-3",
            decision_value="approved",
            reviewer_id="reviewer-a",
            justification="Claim is within acceptable bounds",
        ),
    ]


# --- Tests ---


@pytest.mark.anyio
async def test_successful_insertion_and_decision_reading(
    base_state: PipelineState, sample_decisions: list[Decision]
):
    """Human review should insert escalated claims and read decisions on resume."""
    queue_writer = MockApprovalQueueWriter()
    decision_reader = MockDecisionReader(sample_decisions)
    interrupt_handler = MockInterruptHandler()

    result = await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    # Verify claims were inserted into approval queue
    assert len(queue_writer.inserted) == 1
    inserted_claim_ids, inserted_run_id = queue_writer.inserted[0]
    assert set(inserted_claim_ids) == {"c3", "c4", "c5"}
    assert inserted_run_id == "test-run-id"

    # Verify interrupt was called
    assert interrupt_handler.call_count == 1

    # Verify decisions are populated
    assert result["decisions"] == sample_decisions
    assert result["node_status"] == "completed"


@pytest.mark.anyio
async def test_completed_nodes_includes_human_review(
    base_state: PipelineState, sample_decisions: list[Decision]
):
    """completed_nodes should include 'human_review' on success."""
    queue_writer = MockApprovalQueueWriter()
    decision_reader = MockDecisionReader(sample_decisions)
    interrupt_handler = MockInterruptHandler()

    result = await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    assert "human_review" in result["completed_nodes"]
    assert result["completed_nodes"] == [
        "ingest",
        "extract_text",
        "chunk",
        "route_to_queue",
        "human_review",
    ]


@pytest.mark.anyio
async def test_decisions_properly_populated_in_state(
    base_state: PipelineState, sample_decisions: list[Decision]
):
    """Decisions returned by the reader should be stored in state['decisions']."""
    queue_writer = MockApprovalQueueWriter()
    decision_reader = MockDecisionReader(sample_decisions)
    interrupt_handler = MockInterruptHandler()

    result = await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    assert len(result["decisions"]) == 3
    # Check each decision has the expected structure
    for decision in result["decisions"]:
        assert "claim_id" in decision
        assert "approval_queue_id" in decision
        assert "decision_value" in decision
        assert "reviewer_id" in decision
        assert "justification" in decision

    # Verify specific decisions
    approved_ids = [
        d["claim_id"] for d in result["decisions"] if d["decision_value"] == "approved"
    ]
    rejected_ids = [
        d["claim_id"] for d in result["decisions"] if d["decision_value"] == "rejected"
    ]
    assert set(approved_ids) == {"c3", "c5"}
    assert set(rejected_ids) == {"c4"}


@pytest.mark.anyio
async def test_interrupt_handler_called(base_state: PipelineState):
    """The interrupt handler should be called exactly once during execution."""
    queue_writer = MockApprovalQueueWriter()
    decision_reader = MockDecisionReader([])
    interrupt_handler = MockInterruptHandler()

    await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    assert interrupt_handler.call_count == 1


@pytest.mark.anyio
async def test_current_node_set_to_human_review(
    base_state: PipelineState, sample_decisions: list[Decision]
):
    """current_node should be set to 'human_review' on completion."""
    queue_writer = MockApprovalQueueWriter()
    decision_reader = MockDecisionReader(sample_decisions)
    interrupt_handler = MockInterruptHandler()

    result = await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    assert result["current_node"] == "human_review"


@pytest.mark.anyio
async def test_error_cleared_on_success(
    base_state: PipelineState, sample_decisions: list[Decision]
):
    """error_type and error_detail should be None on successful completion."""
    queue_writer = MockApprovalQueueWriter()
    decision_reader = MockDecisionReader(sample_decisions)
    interrupt_handler = MockInterruptHandler()

    result = await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    assert result["error_type"] is None
    assert result["error_detail"] is None


@pytest.mark.anyio
async def test_queue_writer_failure_returns_transient_error(
    base_state: PipelineState,
):
    """If queue writer fails, node should return transient error."""
    queue_writer = FailingQueueWriter()
    decision_reader = MockDecisionReader([])
    interrupt_handler = MockInterruptHandler()

    result = await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert "Database connection failed" in result["error_detail"]
    assert result["current_node"] == "human_review"
    # interrupt should NOT have been called since failure was before it
    assert interrupt_handler.call_count == 0


@pytest.mark.anyio
async def test_decision_reader_failure_returns_transient_error(
    base_state: PipelineState,
):
    """If decision reader fails after resume, node should return transient error."""
    queue_writer = MockApprovalQueueWriter()
    decision_reader = FailingDecisionReader()
    interrupt_handler = MockInterruptHandler()

    result = await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert "Decision table unreachable" in result["error_detail"]
    assert result["current_node"] == "human_review"
    # Interrupt should have been called (failure happened after)
    assert interrupt_handler.call_count == 1


@pytest.mark.anyio
async def test_empty_decisions_still_completes(base_state: PipelineState):
    """If decision reader returns empty list, node should still complete."""
    queue_writer = MockApprovalQueueWriter()
    decision_reader = MockDecisionReader([])
    interrupt_handler = MockInterruptHandler()

    result = await human_review(
        base_state,
        queue_writer=queue_writer,
        decision_reader=decision_reader,
        interrupt_handler=interrupt_handler,
    )

    assert result["node_status"] == "completed"
    assert result["decisions"] == []
    assert "human_review" in result["completed_nodes"]
