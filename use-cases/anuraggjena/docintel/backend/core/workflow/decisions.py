"""
Workflow Decision Engine.

Implements agentic decision-making for workflow execution paths.
"""

from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass

from backend.logging_config import get_logger

logger = get_logger(__name__)


class WorkflowDecision(str, Enum):
    """
    Workflow execution decisions.

    Determines the next action based on stage results and workflow state.
    """
    CONTINUE = "continue"              # Normal progression to next stage
    RETRY = "retry"                    # Temporary failure, retry with backoff
    SKIP = "skip"                      # No work needed, bypass stage
    ESCALATE = "escalate"              # Critical issue, human intervention required
    TARGETED_UPDATE = "targeted_update"  # Focused update path detected
    BLOCK = "block"                    # Permanent failure, cannot proceed


@dataclass
class DecisionContext:
    """Context for decision-making."""
    stage_name: str
    stage_result: Dict[str, Any]
    workflow_state: Dict[str, Any]
    retry_count: int = 0
    error: Optional[Exception] = None


@dataclass
class DecisionResult:
    """Result of decision engine evaluation."""
    decision: WorkflowDecision
    reason: str
    metadata: Dict[str, Any]
    next_action: Optional[str] = None


class DecisionEngine:
    """
    Determines workflow execution paths based on stage results.

    Implements intelligent decision-making for:
    - Retry vs. block on errors
    - Skip vs. continue for empty results
    - Escalate vs. block for quality issues
    - Targeted updates vs. full reruns
    """

    def __init__(self, max_retries: int = 3):
        """
        Initialize decision engine.

        Args:
            max_retries: Maximum retry attempts for transient failures
        """
        self.max_retries = max_retries

    async def decide(self, context: DecisionContext) -> DecisionResult:
        """
        Make decision based on stage result and workflow state.

        Args:
            context: Decision context with stage result and state

        Returns:
            DecisionResult with decision type, reason, and metadata

        Decision tree:
        1. Check for errors (retry or block)
        2. Check for quality gate blocks (escalate or block)
        3. Check for focused update conditions (targeted_update)
        4. Check for empty results (skip or continue)
        5. Default to continue
        """
        logger.info(
            "evaluating_decision",
            stage=context.stage_name,
            retry_count=context.retry_count
        )

        # Check for errors
        if context.error:
            return await self._handle_error(context)

        # Check for quality gate blocks
        if self._is_quality_gate_blocked(context.stage_result):
            return await self._handle_quality_block(context)

        # Check for focused update conditions
        if self._is_focused_update(context.workflow_state):
            return await self._handle_focused_update(context)

        # Check for empty/skippable results
        if self._is_skippable(context.stage_result):
            return DecisionResult(
                decision=WorkflowDecision.SKIP,
                reason="No actionable results from stage",
                metadata={
                    "stage": context.stage_name,
                    "result_empty": True
                },
                next_action="skip_to_next"
            )

        # Default: continue (using stage-provided reason if specified)
        default_reason = context.stage_result.get("decision_reason", "Stage completed successfully")
        return DecisionResult(
            decision=WorkflowDecision.CONTINUE,
            reason=default_reason,
            metadata={"stage": context.stage_name},
            next_action="proceed"
        )

    async def _handle_error(self, context: DecisionContext) -> DecisionResult:
        """Handle error conditions with retry logic."""
        error = context.error

        # Check if error is retryable
        is_retryable = self._is_retryable_error(error)

        if is_retryable and context.retry_count < self.max_retries:
            # Retry with exponential backoff
            backoff_seconds = 2 ** context.retry_count

            logger.info(
                "deciding_retry",
                stage=context.stage_name,
                retry_count=context.retry_count,
                backoff_seconds=backoff_seconds
            )

            return DecisionResult(
                decision=WorkflowDecision.RETRY,
                reason=f"Transient error: {str(error)}",
                metadata={
                    "error_type": type(error).__name__,
                    "retry_count": context.retry_count,
                    "backoff_seconds": backoff_seconds
                },
                next_action="retry_with_backoff"
            )

        else:
            # Permanent failure or max retries exceeded
            logger.error(
                "deciding_block",
                stage=context.stage_name,
                error=str(error),
                retry_count=context.retry_count
            )

            return DecisionResult(
                decision=WorkflowDecision.BLOCK,
                reason=f"Permanent failure: {str(error)}",
                metadata={
                    "error_type": type(error).__name__,
                    "retry_count": context.retry_count,
                    "max_retries_exceeded": context.retry_count >= self.max_retries
                },
                next_action="fail_workflow"
            )

    async def _handle_quality_block(
        self,
        context: DecisionContext
    ) -> DecisionResult:
        """Handle quality gate blocks."""
        result = context.stage_result
        blocking_reason = result.get("blocking_reason", "unknown")

        # Check if it's a contradiction (escalate to human)
        if "contradiction" in blocking_reason.lower():
            logger.warning(
                "deciding_escalate",
                stage=context.stage_name,
                reason=blocking_reason
            )

            return DecisionResult(
                decision=WorkflowDecision.ESCALATE,
                reason=f"Contradiction detected: {blocking_reason}",
                metadata={
                    "blocking_reason": blocking_reason,
                    "requires_human_review": True
                },
                next_action="wait_for_human"
            )

        # Other quality issues: block
        logger.error(
            "deciding_block_quality",
            stage=context.stage_name,
            reason=blocking_reason
        )

        return DecisionResult(
            decision=WorkflowDecision.BLOCK,
            reason=f"Quality gate failed: {blocking_reason}",
            metadata={"blocking_reason": blocking_reason},
            next_action="fail_workflow"
        )

    async def _handle_focused_update(
        self,
        context: DecisionContext
    ) -> DecisionResult:
        """Handle focused update path."""
        state = context.workflow_state

        unchanged_count = state.get("unchanged_claims_count", 0)
        affected_count = state.get("affected_claims_count", 0)

        logger.info(
            "deciding_targeted_update",
            stage=context.stage_name,
            unchanged=unchanged_count,
            affected=affected_count
        )

        return DecisionResult(
            decision=WorkflowDecision.TARGETED_UPDATE,
            reason="Focused update detected - preserve unchanged content",
            metadata={
                "unchanged_count": unchanged_count,
                "affected_count": affected_count,
                "baseline_run_id": state.get("baseline_run_id")
            },
            next_action="focused_update_path"
        )

    def _is_retryable_error(self, error: Exception) -> bool:
        """Determine if error is retryable."""
        retryable_errors = (
            TimeoutError,
            ConnectionError,
            # Add more retryable error types
        )

        # Check error type
        if isinstance(error, retryable_errors):
            return True

        # Check error message for common transient patterns
        error_msg = str(error).lower()
        transient_patterns = [
            "timeout",
            "connection",
            "temporary",
            "rate limit",
            "503",
            "429"
        ]

        return any(pattern in error_msg for pattern in transient_patterns)

    def _is_quality_gate_blocked(self, stage_result: Dict[str, Any]) -> bool:
        """Check if quality gate blocked execution."""
        return (
            stage_result.get("quality_gate_blocked", False) or
            stage_result.get("blocked", False)
        )

    def _is_focused_update(self, workflow_state: Dict[str, Any]) -> bool:
        """Check if workflow is a focused update."""
        return (
            workflow_state.get("is_focused_update", False) and
            workflow_state.get("baseline_run_id") is not None
        )

    def _is_skippable(self, stage_result: Dict[str, Any]) -> bool:
        """Check if stage result is empty/skippable."""
        # Check for explicit skip flag
        if stage_result.get("skip", False):
            return True

        # Check for empty results - only if results_count is explicitly present
        if "results_count" in stage_result:
            results_count = stage_result["results_count"]
            if results_count == 0:
                # But don't skip if it's an error
                if stage_result.get("error"):
                    return False
                return True

        # Check for all unchanged in focused update
        unchanged_count = stage_result.get("unchanged_count", 0)
        total_count = stage_result.get("total_count", 0)

        if total_count > 0 and unchanged_count == total_count:
            return True

        return False


class DecisionMetrics:
    """Track decision metrics for observability."""

    def __init__(self):
        """Initialize metrics tracker."""
        self.decisions: Dict[WorkflowDecision, int] = {
            decision: 0 for decision in WorkflowDecision
        }

    def record_decision(self, decision: WorkflowDecision) -> None:
        """Record a decision for metrics."""
        self.decisions[decision] += 1

    def get_metrics(self) -> Dict[str, int]:
        """Get decision metrics."""
        return {
            decision.value: count
            for decision, count in self.decisions.items()
        }

    def reset(self) -> None:
        """Reset metrics."""
        self.decisions = {decision: 0 for decision in WorkflowDecision}
