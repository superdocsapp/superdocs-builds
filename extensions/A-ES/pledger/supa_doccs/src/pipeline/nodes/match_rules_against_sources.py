"""Match rules against sources node — evaluates compliance rules against source spans.

This node evaluates rules directly against source document spans (chunks)
rather than extracted claims. It is the parallel companion to the existing
match_rules node. Both nodes run concurrently after extract_claims and
converge at merge_findings before score_confidence.

Rules are partitioned by check_type:
- LLM rules are batched per span via evaluate_batch() to reduce API calls.
- Structured rules use the structured evaluator if supported, else fall back
  to LLM with a warning.

Only violations (verdict == "fail") produce findings. No padding, no forced
findings.

Empty inputs (no rules or no chunks) → empty findings, status "completed".
LLM API failure → transient error state for retry.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from src.pipeline.evaluators import LLMEvaluator, StructuredEvaluator
from src.pipeline.findings import EvaluationResult, Finding
from src.pipeline.playbook import RuleDefinition
from src.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


async def match_rules_against_sources(
    state: PipelineState,
    *,
    llm_evaluator: Optional[LLMEvaluator] = None,
    structured_evaluator: Optional[StructuredEvaluator] = None,
) -> PipelineState:
    """Evaluate compliance rules directly against source document spans.

    Reads source_rules and chunks from state, partitions rules by check_type,
    evaluates each rule against available source spans, and produces findings
    only for violations (verdict == "fail").

    Args:
        state: Pipeline state containing source_rules (list of RuleDefinition
            dicts) and chunks (list of ChunkEntry dicts).
        llm_evaluator: LLM-based evaluator for rules with check_type "llm".
            Required if any LLM rules are present.
        structured_evaluator: Structured evaluator for rules with check_type
            "structured". Optional; unsupported rules fall back to LLM.

    Returns:
        Updated PipelineState with source_findings populated. On success,
        node_status is "completed". On LLM API failure, node_status is
        "error" with error_type "transient".
    """
    source_rules_raw: list[dict[str, Any]] = state.get("source_rules", [])
    chunks: list[dict[str, Any]] = state.get("chunks", [])

    # Reconstruct RuleDefinition models from serialized dicts
    source_rules: list[RuleDefinition] = []
    for rule_dict in source_rules_raw:
        try:
            source_rules.append(RuleDefinition.model_validate(rule_dict))
        except Exception:
            # Skip malformed rule entries (shouldn't happen if partitioner worked)
            logger.warning("Skipping malformed rule entry: %s", rule_dict)
            continue

    # No applicable rules → empty findings, completed
    if not source_rules:
        return _completed_state(state, source_findings=[])

    # No source spans available → empty findings, completed
    if not chunks:
        return _completed_state(state, source_findings=[])

    findings: list[Finding] = []

    try:
        for chunk in chunks:
            span_text: str = chunk["text"]
            span_offset: int = chunk["start_offset"]

            # Partition rules by check_type for this span
            llm_rules: list[RuleDefinition] = []
            structured_rules: list[RuleDefinition] = []

            for rule in source_rules:
                if rule.check_type == "structured":
                    if (
                        structured_evaluator is not None
                        and structured_evaluator.supports(rule)
                    ):
                        structured_rules.append(rule)
                    else:
                        # Fall back to LLM for unsupported structured rules
                        logger.warning(
                            "Structured evaluator does not support rule "
                            "'%s', falling back to LLM",
                            rule.id,
                        )
                        llm_rules.append(rule)
                else:
                    llm_rules.append(rule)

            # Batch LLM evaluation (multiple rules per span)
            if llm_rules and llm_evaluator is not None:
                results: list[EvaluationResult] = (
                    await llm_evaluator.evaluate_batch(
                        llm_rules, span_text, span_offset
                    )
                )
                for result in results:
                    if result.verdict == "fail":
                        findings.append(_result_to_finding(result))

            # Individual structured evaluations
            if structured_evaluator is not None:
                for rule in structured_rules:
                    result = await structured_evaluator.evaluate(
                        rule, span_text, span_offset
                    )
                    if result.verdict == "fail":
                        findings.append(_result_to_finding(result))

    except Exception as exc:
        # LLM API failure → transient error
        return _transient_error_state(
            state,
            error_detail=f"LLM API failure during source rule evaluation: {exc}",
        )

    return _completed_state(state, source_findings=findings)


def _result_to_finding(result: EvaluationResult) -> Finding:
    """Convert a failing EvaluationResult to a Finding.

    Args:
        result: An EvaluationResult with verdict == "fail".

    Returns:
        A Finding dataclass with all provenance fields populated.
    """
    return Finding(
        rule_id=result.rule_id,
        verdict="fail",
        cited_span=result.cited_span,
        explanation=result.explanation,
        evaluation_method=result.evaluation_method,
    )


def _serialize_findings(findings: list[Finding]) -> list[dict[str, Any]]:
    """Serialize Finding dataclasses to dicts for state storage.

    Args:
        findings: List of Finding dataclasses.

    Returns:
        List of serialized dicts suitable for PipelineState storage.
    """
    return [asdict(f) for f in findings]


def _completed_state(
    state: PipelineState, *, source_findings: list[Finding]
) -> PipelineState:
    """Return completed state with source_findings populated.

    Args:
        state: Current pipeline state.
        source_findings: List of Finding objects to serialize into state.

    Returns:
        Updated PipelineState with node_status "completed".
    """
    completed_nodes = list(state.get("completed_nodes", []))
    completed_nodes.append("match_rules_against_sources")

    return PipelineState(
        **{
            **state,
            "source_findings": _serialize_findings(source_findings),
            "current_node": "match_rules_against_sources",
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed_nodes,
        }
    )


def _transient_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a transient error state for retry.

    Transient errors are retryable (e.g., LLM API timeouts, rate limits).

    Args:
        state: Current pipeline state.
        error_detail: Description of the error that occurred.

    Returns:
        Updated PipelineState with node_status "error" and error_type "transient".
    """
    return PipelineState(
        **{
            **state,
            "current_node": "match_rules_against_sources",
            "node_status": "error",
            "error_type": "transient",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),
        }
    )
