"""Score confidence node — refines confidence scores and flags claims for review.

This is the final node of the Examine Stage. It refines confidence scores for
each claim-verdict pair by evaluating verdict classification certainty and
source location completeness. Claims below the configured confidence threshold
are flagged with needs_human_review=True.

Non-compliant verdicts always get needs_human_review=True regardless of confidence.
"""

from __future__ import annotations

from typing import Optional, Protocol

from src.pipeline.state import ChunkEntry, ComplianceVerdict, PipelineState


class ConfidenceScoringService(Protocol):
    """Protocol for refining confidence scores on verdicts.

    Implementations may use LLM-based analysis, heuristic rules, or
    any other scoring logic to refine the confidence values.
    """

    async def refine_scores(
        self, verdicts: list[ComplianceVerdict], chunks: list[ChunkEntry]
    ) -> list[ComplianceVerdict]:
        """Refine confidence scores for verdicts based on chunks context.

        Args:
            verdicts: List of compliance verdicts with preliminary confidence scores.
            chunks: List of chunk entries providing source location context.

        Returns:
            List of compliance verdicts with refined confidence scores.

        Raises:
            Exception: If the scoring service encounters an API failure.
        """
        ...


async def score_confidence(
    state: PipelineState,
    *,
    scoring_service: Optional[ConfidenceScoringService] = None,
) -> PipelineState:
    """Refine confidence scores and flag claims for human review.

    Iterates through verdicts, optionally refining scores via an injectable
    scoring service, then applies threshold flagging:
    - confidence < config["confidence_threshold"] → needs_human_review = True
    - confidence >= config["confidence_threshold"] → needs_human_review = False
    - verdict == "non_compliant" → needs_human_review = True (always)

    Empty verdicts list results in completed status (not error).

    Args:
        state: The current pipeline state containing verdicts, chunks, and config.
        scoring_service: Optional confidence scoring service implementation.
            If None, existing confidence scores are kept and only threshold
            flagging logic is applied.

    Returns:
        Updated PipelineState with refined verdicts, current_node, node_status,
        and completed_nodes set appropriately.
    """
    verdicts = list(state.get("verdicts", []))
    chunks = list(state.get("chunks", []))
    config = state.get("config")

    # Validate config is present and has confidence_threshold
    if config is None:
        return _permanent_error_state(
            state, error_detail="Pipeline config is missing"
        )

    try:
        threshold = config["confidence_threshold"]
    except (KeyError, TypeError) as exc:
        return _permanent_error_state(
            state,
            error_detail=f"Rule config issue: confidence_threshold not accessible: {exc}",
        )

    # Empty verdicts → completed with empty verdicts (not error)
    if not verdicts:
        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append("score_confidence")
        return PipelineState(
            **{
                **state,
                "verdicts": [],
                "current_node": "score_confidence",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    # Refine scores via scoring service if provided
    if scoring_service is not None:
        try:
            verdicts = await scoring_service.refine_scores(verdicts, chunks)
        except Exception as exc:
            return _transient_error_state(
                state,
                error_detail=f"Scoring service failure: {exc}",
            )

    # Apply threshold flagging logic
    flagged_verdicts: list[ComplianceVerdict] = []
    for verdict in verdicts:
        updated = dict(verdict)
        confidence = updated.get("confidence", 0.0)

        if updated.get("verdict") == "non_compliant":
            # Non-compliant verdicts always need human review
            updated["needs_human_review"] = True
        elif confidence < threshold:
            updated["needs_human_review"] = True
        else:
            updated["needs_human_review"] = False

        flagged_verdicts.append(ComplianceVerdict(**updated))  # type: ignore[typeddict-item]

    # Success
    completed_nodes = list(state.get("completed_nodes", []))
    completed_nodes.append("score_confidence")

    return PipelineState(
        **{
            **state,
            "verdicts": flagged_verdicts,
            "current_node": "score_confidence",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed_nodes,
        }
    )


def _transient_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a transient error state for score_confidence (LLM API failure)."""
    return PipelineState(
        **{
            **state,
            "current_node": "score_confidence",
            "node_status": "error",
            "error_type": "transient",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )


def _permanent_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a permanent error state for score_confidence (rule config issue)."""
    return PipelineState(
        **{
            **state,
            "current_node": "score_confidence",
            "node_status": "error",
            "error_type": "permanent",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )
