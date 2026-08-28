"""Merge findings node — combines findings from both rule-checking paths.

This node runs after both `match_rules` (claim-based) and
`match_rules_against_sources` (source-span-based) complete. It concatenates
their results into a single `findings` list with no deduplication — both
perspectives are valid and preserved.
"""

from __future__ import annotations

from src.pipeline.state import PipelineState


async def merge_findings(state: PipelineState) -> PipelineState:
    """Merge findings from both rule-checking nodes.

    Concatenates claim-based findings and source-based findings
    into a single list. No deduplication — both perspectives are valid.

    Args:
        state: Pipeline state after both match_rules nodes complete.

    Returns:
        Updated state with merged findings list, current_node set to
        "merge_findings", node_status "completed", and the node name
        appended to completed_nodes.
    """
    claim_findings = state.get("claim_findings", [])
    source_findings = state.get("source_findings", [])

    merged = claim_findings + source_findings

    completed_nodes = list(state.get("completed_nodes", []))
    completed_nodes.append("merge_findings")

    return PipelineState(
        **{
            **state,
            "findings": merged,
            "current_node": "merge_findings",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed_nodes,
        }
    )
