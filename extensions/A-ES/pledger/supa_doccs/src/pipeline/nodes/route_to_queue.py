"""Route-to-queue node — partitions claims into auto_approve, escalate, and auto_reject buckets.

This is the first node of the Stay-Alive Stage. It reads the verdicts list
from State and partitions claims into three queue buckets based on compliance
status, confidence, review flags, and duplicate detection.

Partitioning logic:
1. escalate: non-compliant OR confidence < threshold OR needs_human_review=True
   OR originating from permanent-error escalation
2. auto_reject: duplicate claims within the same run (matching claim_text,
   chunk_index, start_offset, end_offset)
3. auto_approve: compliant AND confidence >= threshold AND NOT needs_human_review

Priority ordering for claims matching multiple conditions:
  escalate > auto_reject > auto_approve
"""

from __future__ import annotations

from src.pipeline.state import (
    ComplianceVerdict,
    ExtractionResult,
    PipelineState,
    QueueBuckets,
)


async def route_to_queue(state: PipelineState) -> PipelineState:
    """Partition claims into queue buckets for downstream processing.

    Reads verdicts and claims from state, applies partitioning rules,
    and populates queue_buckets with claim IDs in the appropriate bucket.

    Args:
        state: The current pipeline state containing verdicts, claims, and config.

    Returns:
        Updated PipelineState with queue_buckets populated, current_node set,
        node_status set, and completed_nodes updated.
    """
    try:
        verdicts = list(state.get("verdicts", []))
        claims = list(state.get("claims", []))
        config = state.get("config")

        # Get the confidence threshold from config
        threshold = config["confidence_threshold"] if config else 0.7

        # Check if we arrived here from a permanent error escalation
        from_permanent_error = (
            state.get("error_type") == "permanent"
        )

        # Build a lookup of claim_id -> verdict
        verdict_by_claim: dict[str, ComplianceVerdict] = {}
        for v in verdicts:
            verdict_by_claim[v["claim_id"]] = v

        # Detect duplicates within this run
        # A claim is a duplicate if another claim in the same run has matching
        # claim_text AND chunk_index AND start_offset AND end_offset
        duplicate_claim_ids = _find_duplicate_claim_ids(claims)

        # Partition claims into buckets with priority: escalate > auto_reject > auto_approve
        auto_approve: list[str] = []
        escalate: list[str] = []
        auto_reject: list[str] = []

        for claim in claims:
            claim_id = claim["claim_id"]
            verdict_entry = verdict_by_claim.get(claim_id)

            # Determine escalation conditions
            should_escalate = False

            if from_permanent_error:
                # All claims escalate when arriving from permanent error
                should_escalate = True
            elif verdict_entry is not None:
                if verdict_entry["verdict"] == "non_compliant":
                    should_escalate = True
                elif verdict_entry["confidence"] < threshold:
                    should_escalate = True
                elif verdict_entry.get("needs_human_review", False):
                    should_escalate = True

            # Determine duplicate condition
            is_duplicate = claim_id in duplicate_claim_ids

            # Apply priority: escalate > auto_reject > auto_approve
            if should_escalate:
                escalate.append(claim_id)
            elif is_duplicate:
                auto_reject.append(claim_id)
            else:
                # Default: auto_approve if compliant with sufficient confidence
                if verdict_entry is not None:
                    if (
                        verdict_entry["verdict"] == "compliant"
                        and verdict_entry["confidence"] >= threshold
                        and not verdict_entry.get("needs_human_review", False)
                    ):
                        auto_approve.append(claim_id)
                    else:
                        # If no clear bucket matches, escalate (safest default)
                        escalate.append(claim_id)
                else:
                    # No verdict for this claim — escalate for safety
                    escalate.append(claim_id)

        # Build queue buckets
        queue_buckets = QueueBuckets(
            auto_approve=auto_approve,
            escalate=escalate,
            auto_reject=auto_reject,
        )

        # Success
        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append("route_to_queue")

        return PipelineState(
            **{
                **state,
                "queue_buckets": queue_buckets,
                "current_node": "route_to_queue",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    except Exception as exc:
        # Any resource failure during partitioning is transient
        return _transient_error_state(
            state,
            error_detail=f"Resource failure during partitioning: {exc}",
        )


def _find_duplicate_claim_ids(claims: list[ExtractionResult]) -> set[str]:
    """Find claim IDs that are duplicates within the same run.

    A claim is a duplicate if another claim in the same run has matching
    claim_text AND chunk_index AND start_offset AND end_offset.

    When duplicates are detected, all but the first occurrence (by list order)
    are marked as duplicates.

    Returns:
        Set of claim_ids that are duplicates (not including the first occurrence).
    """
    seen: dict[tuple[str, int, int, int], str] = {}
    duplicates: set[str] = set()

    for claim in claims:
        key = (
            claim["claim_text"],
            claim["chunk_index"],
            claim["start_offset"],
            claim["end_offset"],
        )
        if key in seen:
            # This is a duplicate — mark it
            duplicates.add(claim["claim_id"])
        else:
            seen[key] = claim["claim_id"]

    return duplicates


def _transient_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a transient error state for route_to_queue."""
    return PipelineState(
        **{
            **state,
            "current_node": "route_to_queue",
            "node_status": "error",
            "error_type": "transient",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )
