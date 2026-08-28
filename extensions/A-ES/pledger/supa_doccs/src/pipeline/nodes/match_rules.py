"""Match rules node — compares claims against compliance rules.

This is the second node of the Examine Stage. It takes each extracted claim
from the pipeline state and compares it against compliance rules from config
(e.g., maximum APR thresholds, required disclosure checks, prohibited fee
structures). It produces a ComplianceVerdict per claim.

Empty claims list → empty verdicts list (completed, not error).
Transient error on LLM API failure; permanent error on missing/unparseable
rule configuration.
"""

from __future__ import annotations

from typing import Optional, Protocol

from src.pipeline.state import ComplianceVerdict, ExtractionResult, PipelineState


class RuleMatchingService(Protocol):
    """Protocol for matching claims against compliance rules."""

    async def match(self, claim: ExtractionResult) -> ComplianceVerdict:
        """Match a single claim against compliance rules.

        Args:
            claim: The extracted claim to evaluate against rules.

        Returns:
            A ComplianceVerdict with the verdict (compliant, non_compliant,
            or indeterminate), confidence, and supporting evidence.

        Raises:
            Exception: If the LLM API call fails for any reason.
        """
        ...


class RuleConfigError(Exception):
    """Raised when rule configuration is missing or unparseable."""

    pass


async def match_rules(
    state: PipelineState,
    *,
    rule_matching_service: Optional[RuleMatchingService] = None,
) -> PipelineState:
    """Compare each claim against compliance rules and produce verdicts.

    Processes each claim through the rule matching service to determine
    compliance status. Returns a ComplianceVerdict per claim.

    Args:
        state: The current pipeline state containing claims and config.
        rule_matching_service: Optional rule matching service implementation.
            If None, the node returns a permanent error (rule config missing).

    Returns:
        Updated PipelineState with verdicts, current_node, node_status,
        and completed_nodes set appropriately.
    """
    claims = state.get("claims", [])

    # Empty claims → empty verdicts (completed, not error)
    if not claims:
        completed_nodes = list(state.get("completed_nodes", []))
        completed_nodes.append("match_rules")
        return PipelineState(
            **{
                **state,
                "verdicts": [],
                "current_node": "match_rules",
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    # Validate the rule matching service is provided
    if rule_matching_service is None:
        return _permanent_error_state(
            state,
            error_detail="Rule configuration missing: no rule matching service provided",
        )

    # Match each claim against compliance rules
    verdicts: list[ComplianceVerdict] = []
    try:
        for claim in claims:
            # Claims with unverifiable citations get a distinct outcome.
            # Read citation_status directly — NEVER infer from offset values.
            if claim.get("citation_status") == "unverifiable":
                verdicts.append(ComplianceVerdict(
                    claim_id=claim["claim_id"],
                    verdict="indeterminate",
                    confidence=0.0,
                    needs_human_review=True,
                    rule_id=None,
                    evidence_refs=["citation_unverifiable"],
                ))
                continue

            verdict = await rule_matching_service.match(claim)
            verdicts.append(verdict)
    except RuleConfigError as exc:
        # Non-recoverable: rule config is missing or unparseable
        return _permanent_error_state(
            state,
            error_detail=f"Rule configuration error: {exc}",
        )
    except Exception as exc:
        # LLM API failure — transient, retryable
        return _transient_error_state(
            state,
            error_detail=f"LLM API failure during rule matching: {exc}",
        )

    # Success — all claims matched
    completed_nodes = list(state.get("completed_nodes", []))
    completed_nodes.append("match_rules")

    return PipelineState(
        **{
            **state,
            "verdicts": verdicts,
            "current_node": "match_rules",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed_nodes,
        }
    )


def _transient_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a transient error state for the match_rules node.

    Transient errors are retryable (e.g., LLM API timeouts, rate limits).
    """
    return PipelineState(
        **{
            **state,
            "current_node": "match_rules",
            "node_status": "error",
            "error_type": "transient",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )


def _permanent_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a permanent error state for the match_rules node.

    Permanent errors are not retryable (e.g., missing/unparseable rule config).
    """
    return PipelineState(
        **{
            **state,
            "current_node": "match_rules",
            "node_status": "error",
            "error_type": "permanent",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )
