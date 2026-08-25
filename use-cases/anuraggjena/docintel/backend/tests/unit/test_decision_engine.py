"""
Unit tests for DecisionEngine.

Tests all six decision types and their logic.
"""

import pytest
from backend.core.workflow.decisions import (
    DecisionEngine,
    DecisionContext,
    WorkflowDecision
)


class TestDecisionEngine:
    """Test DecisionEngine decision logic."""

    @pytest.fixture
    def engine(self):
        """Create decision engine with max 3 retries."""
        return DecisionEngine(max_retries=3)

    @pytest.mark.asyncio
    async def test_continue_on_success(self, engine):
        """Test CONTINUE decision on successful stage execution."""
        context = DecisionContext(
            stage_name="test_stage",
            stage_result={"success": True, "data": "result"},
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=0,
            error=None
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.CONTINUE
        assert "successfully" in decision.reason.lower()
        assert decision.next_action == "proceed"

    @pytest.mark.asyncio
    async def test_skip_on_empty_results(self, engine):
        """Test SKIP decision when stage returns empty results."""
        context = DecisionContext(
            stage_name="test_stage",
            stage_result={"results_count": 0},
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=0,
            error=None
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.SKIP
        assert "no actionable results" in decision.reason.lower()
        assert decision.next_action == "skip_to_next"

    @pytest.mark.asyncio
    async def test_skip_on_explicit_skip_flag(self, engine):
        """Test SKIP decision when stage explicitly requests skip."""
        context = DecisionContext(
            stage_name="test_stage",
            stage_result={"skip": True},
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=0,
            error=None
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.SKIP

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self, engine):
        """Test RETRY decision on retryable error."""
        context = DecisionContext(
            stage_name="test_stage",
            stage_result={},
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=0,
            error=TimeoutError("Connection timeout")
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.RETRY
        assert "transient" in decision.reason.lower()
        assert decision.next_action == "retry_with_backoff"
        assert decision.metadata["retry_count"] == 0
        assert decision.metadata["backoff_seconds"] == 1  # 2^0

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(self, engine):
        """Test RETRY uses exponential backoff."""
        contexts = [
            DecisionContext(
                stage_name="test_stage",
                stage_result={},
                workflow_state={"workflow_run_id": "test-123"},
                retry_count=i,
                error=TimeoutError("timeout")
            )
            for i in range(3)
        ]

        decisions = [await engine.decide(ctx) for ctx in contexts]

        # Check exponential backoff: 1, 2, 4 seconds
        assert decisions[0].metadata["backoff_seconds"] == 1
        assert decisions[1].metadata["backoff_seconds"] == 2
        assert decisions[2].metadata["backoff_seconds"] == 4

    @pytest.mark.asyncio
    async def test_block_after_max_retries(self, engine):
        """Test BLOCK decision after max retries exceeded."""
        context = DecisionContext(
            stage_name="test_stage",
            stage_result={},
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=3,  # Equals max_retries
            error=TimeoutError("timeout")
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.BLOCK
        assert "permanent failure" in decision.reason.lower()
        assert decision.next_action == "fail_workflow"
        assert decision.metadata["max_retries_exceeded"] is True

    @pytest.mark.asyncio
    async def test_block_on_non_retryable_error(self, engine):
        """Test BLOCK decision on non-retryable error."""
        context = DecisionContext(
            stage_name="test_stage",
            stage_result={},
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=0,
            error=ValueError("Invalid input data")
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.BLOCK
        assert "permanent failure" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_escalate_on_contradiction(self, engine):
        """Test ESCALATE decision on contradiction detection."""
        context = DecisionContext(
            stage_name="quality_gate",
            stage_result={
                "quality_gate_blocked": True,
                "blocking_reason": "Contradiction detected: HS code mismatch"
            },
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=0,
            error=None
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.ESCALATE
        assert "contradiction" in decision.reason.lower()
        assert decision.next_action == "wait_for_human"
        assert decision.metadata["requires_human_review"] is True

    @pytest.mark.asyncio
    async def test_block_on_quality_gate_failure(self, engine):
        """Test BLOCK decision on non-contradiction quality gate failure."""
        context = DecisionContext(
            stage_name="quality_gate",
            stage_result={
                "quality_gate_blocked": True,
                "blocking_reason": "Confidence too low"
            },
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=0,
            error=None
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.BLOCK
        assert "quality gate failed" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_targeted_update_on_focused_update_flag(self, engine):
        """Test TARGETED_UPDATE decision when focused update detected."""
        context = DecisionContext(
            stage_name="generate",
            stage_result={"success": True},
            workflow_state={
                "workflow_run_id": "test-123",
                "is_focused_update": True,
                "baseline_run_id": "baseline-456",
                "unchanged_claims_count": 5,
                "affected_claims_count": 2
            },
            retry_count=0,
            error=None
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.TARGETED_UPDATE
        assert "focused update" in decision.reason.lower()
        assert decision.next_action == "focused_update_path"
        assert decision.metadata["unchanged_count"] == 5
        assert decision.metadata["affected_count"] == 2
        assert decision.metadata["baseline_run_id"] == "baseline-456"

    @pytest.mark.asyncio
    async def test_retryable_error_patterns(self, engine):
        """Test that common transient error patterns are retryable."""
        transient_errors = [
            ConnectionError("Connection refused"),
            TimeoutError("Request timeout"),
            Exception("503 Service Unavailable"),
            Exception("429 Rate limit exceeded"),
            Exception("Temporary failure"),
        ]

        for error in transient_errors:
            context = DecisionContext(
                stage_name="test_stage",
                stage_result={},
                workflow_state={"workflow_run_id": "test-123"},
                retry_count=0,
                error=error
            )

            decision = await engine.decide(context)
            assert decision.decision == WorkflowDecision.RETRY, \
                f"Expected RETRY for {error}, got {decision.decision}"

    @pytest.mark.asyncio
    async def test_non_retryable_error_patterns(self, engine):
        """Test that permanent errors are not retryable."""
        permanent_errors = [
            ValueError("Invalid input"),
            KeyError("Missing required key"),
            TypeError("Type mismatch"),
            Exception("404 Not found"),
        ]

        for error in permanent_errors:
            context = DecisionContext(
                stage_name="test_stage",
                stage_result={},
                workflow_state={"workflow_run_id": "test-123"},
                retry_count=0,
                error=error
            )

            decision = await engine.decide(context)
            assert decision.decision == WorkflowDecision.BLOCK, \
                f"Expected BLOCK for {error}, got {decision.decision}"

    @pytest.mark.asyncio
    async def test_decision_metadata_completeness(self, engine):
        """Test that decisions include complete metadata."""
        context = DecisionContext(
            stage_name="test_stage",
            stage_result={"data": "test"},
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=1,
            error=TimeoutError("timeout")
        )

        decision = await engine.decide(context)

        # All decisions should have these fields
        assert decision.decision is not None
        assert decision.reason is not None
        assert decision.metadata is not None
        assert isinstance(decision.metadata, dict)

        # Metadata should explain why decision was made
        assert "error_type" in decision.metadata or "stage" in decision.metadata

    @pytest.mark.asyncio
    async def test_skip_on_all_unchanged_focused_update(self, engine):
        """Test SKIP when all claims unchanged in focused update."""
        context = DecisionContext(
            stage_name="generate",
            stage_result={
                "unchanged_count": 10,
                "total_count": 10
            },
            workflow_state={"workflow_run_id": "test-123"},
            retry_count=0,
            error=None
        )

        decision = await engine.decide(context)

        assert decision.decision == WorkflowDecision.SKIP
        assert "no actionable results" in decision.reason.lower()
