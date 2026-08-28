"""Property-based tests for rules-checking node logic.

**Validates: Requirements 2.3, 3.3, 6.1, 6.2, 6.3, 4.3, 9.3**

Property 4: Findings Merge Preserves All Items
Property 5: Empty Inputs Produce Empty Findings
Property 6: Findings Produced If and Only If Verdict Is "fail"
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any
from unittest.mock import AsyncMock

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.findings import CitedSpan, EvaluationResult, Finding
from src.pipeline.nodes.match_rules_against_sources import match_rules_against_sources
from src.pipeline.nodes.merge_findings import merge_findings
from src.pipeline.playbook import RuleDefinition
from src.pipeline.state import (
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


# =============================================================================
# Shared Strategies
# =============================================================================


@st.composite
def valid_cited_spans(draw: st.DrawFn) -> CitedSpan:
    """Generate valid CitedSpan instances where start < end and text is non-empty."""
    start = draw(st.integers(min_value=0, max_value=100_000))
    end = draw(st.integers(min_value=start + 1, max_value=start + 10_000))
    text = draw(
        st.text(
            min_size=1,
            max_size=200,
            alphabet=st.characters(categories=("L", "N", "P", "Z", "S")),
        )
    )
    return CitedSpan(start_offset=start, end_offset=end, text=text)


@st.composite
def valid_finding_dicts(draw: st.DrawFn) -> dict[str, Any]:
    """Generate valid finding dicts (serialized Finding format)."""
    cited_span = draw(valid_cited_spans())
    rule_id = draw(
        st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(categories=("L", "N", "P")),
        )
    )
    explanation = draw(
        st.text(
            min_size=1,
            max_size=200,
            alphabet=st.characters(categories=("L", "N", "P", "Z", "S")),
        )
    )
    evaluation_method = draw(st.sampled_from(["llm", "structured"]))
    return {
        "rule_id": rule_id,
        "verdict": "fail",
        "cited_span": asdict(cited_span),
        "explanation": explanation,
        "evaluation_method": evaluation_method,
    }


def _make_config() -> PipelineConfig:
    """Create a default PipelineConfig for testing."""
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


def _make_base_state(**overrides: Any) -> PipelineState:
    """Create a minimal PipelineState with optional overrides."""
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=_make_config(),
    )
    if overrides:
        state = PipelineState(**{**state, **overrides})
    return state


# =============================================================================
# Property 4: Findings Merge Preserves All Items
# =============================================================================


@given(
    claim_findings=st.lists(valid_finding_dicts(), min_size=0, max_size=20),
    source_findings=st.lists(valid_finding_dicts(), min_size=0, max_size=20),
)
@settings(max_examples=200)
def test_findings_merge_preserves_all_items(
    claim_findings: list[dict[str, Any]],
    source_findings: list[dict[str, Any]],
) -> None:
    """Property 4: Findings Merge Preserves All Items.

    **Validates: Requirements 2.3**

    For any two lists of findings (from claim-based and source-based evaluation),
    the merged list SHALL have length equal to the sum of both input lengths and
    contain every item from both inputs.
    """
    state = _make_base_state(
        claim_findings=claim_findings,
        source_findings=source_findings,
    )

    result_state = asyncio.run(merge_findings(state))

    merged = result_state["findings"]

    # Length must equal sum of inputs
    assert len(merged) == len(claim_findings) + len(source_findings), (
        f"Expected merged length {len(claim_findings) + len(source_findings)}, "
        f"got {len(merged)}"
    )

    # All claim_findings items must be present in merged
    for item in claim_findings:
        assert item in merged, (
            f"Claim finding {item['rule_id']} not found in merged list"
        )

    # All source_findings items must be present in merged
    for item in source_findings:
        assert item in merged, (
            f"Source finding {item['rule_id']} not found in merged list"
        )


# =============================================================================
# Property 5: Empty Inputs Produce Empty Findings
# =============================================================================


@st.composite
def valid_rule_dicts(draw: st.DrawFn) -> dict[str, Any]:
    """Generate valid serialized RuleDefinition dicts for state storage."""
    rule_id = draw(
        st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(categories=("L", "N")),
        )
    )
    scope = draw(st.sampled_from(["source", "both"]))
    check_type = draw(st.sampled_from(["llm", "structured"]))
    return {
        "id": rule_id,
        "description": "Test rule description",
        "check_description": "Check something in the document",
        "scope": scope,
        "check_type": check_type,
    }


@st.composite
def valid_chunk_dicts(draw: st.DrawFn) -> dict[str, Any]:
    """Generate valid chunk entry dicts for state storage."""
    text = draw(
        st.text(
            min_size=1,
            max_size=500,
            alphabet=st.characters(categories=("L", "N", "P", "Z", "S")),
        )
    )
    start_offset = draw(st.integers(min_value=0, max_value=10000))
    return {
        "index": draw(st.integers(min_value=0, max_value=50)),
        "text": text,
        "start_offset": start_offset,
        "end_offset": start_offset + len(text),
    }


@given(chunks=st.lists(valid_chunk_dicts(), min_size=1, max_size=5))
@settings(max_examples=100)
def test_empty_source_rules_produce_empty_findings(
    chunks: list[dict[str, Any]],
) -> None:
    """Property 5: Empty source_rules + valid chunks → empty findings.

    **Validates: Requirements 3.3, 9.3**

    When source_rules is empty but chunks are present, the node SHALL
    return an empty findings list with node_status "completed".
    """
    state = _make_base_state(
        source_rules=[],
        chunks=chunks,
    )

    result_state = asyncio.run(match_rules_against_sources(state))

    assert result_state["source_findings"] == [], (
        f"Expected empty source_findings, got {result_state['source_findings']}"
    )
    assert result_state["node_status"] == "completed", (
        f"Expected node_status 'completed', got '{result_state['node_status']}'"
    )


@given(source_rules=st.lists(valid_rule_dicts(), min_size=1, max_size=5))
@settings(max_examples=100)
def test_empty_chunks_produce_empty_findings(
    source_rules: list[dict[str, Any]],
) -> None:
    """Property 5: Valid source_rules + empty chunks → empty findings.

    **Validates: Requirements 3.3, 9.3**

    When chunks is empty but source_rules are present, the node SHALL
    return an empty findings list with node_status "completed".
    """
    state = _make_base_state(
        source_rules=source_rules,
        chunks=[],
    )

    result_state = asyncio.run(match_rules_against_sources(state))

    assert result_state["source_findings"] == [], (
        f"Expected empty source_findings, got {result_state['source_findings']}"
    )
    assert result_state["node_status"] == "completed", (
        f"Expected node_status 'completed', got '{result_state['node_status']}'"
    )


# =============================================================================
# Property 6: Findings Produced If and Only If Verdict Is "fail"
# =============================================================================


@st.composite
def evaluation_results_with_random_verdicts(
    draw: st.DrawFn,
) -> list[EvaluationResult]:
    """Generate a list of EvaluationResult objects with random verdicts."""
    num_results = draw(st.integers(min_value=1, max_value=15))
    results: list[EvaluationResult] = []

    for i in range(num_results):
        rule_id = f"RULE-{i:03d}"
        verdict = draw(
            st.sampled_from(["pass", "fail", "not_applicable", "insufficient_evidence"])
        )
        start = draw(st.integers(min_value=0, max_value=500))
        end = draw(st.integers(min_value=start + 1, max_value=start + 200))
        text = draw(
            st.text(
                min_size=1,
                max_size=100,
                alphabet=st.characters(categories=("L", "N", "P", "Z")),
            )
        )
        explanation = draw(
            st.text(
                min_size=1,
                max_size=100,
                alphabet=st.characters(categories=("L", "N", "P", "Z")),
            )
        )
        evaluation_method = draw(st.sampled_from(["llm", "structured"]))

        results.append(
            EvaluationResult(
                rule_id=rule_id,
                verdict=verdict,
                cited_span=CitedSpan(
                    start_offset=start, end_offset=end, text=text
                ),
                explanation=explanation,
                evaluation_method=evaluation_method,
            )
        )

    return results


@given(eval_results=evaluation_results_with_random_verdicts())
@settings(max_examples=200)
def test_findings_produced_if_and_only_if_verdict_is_fail(
    eval_results: list[EvaluationResult],
) -> None:
    """Property 6: Findings Produced If and Only If Verdict Is "fail".

    **Validates: Requirements 6.1, 6.2, 6.3, 4.3**

    For any list of EvaluationResult instances returned by evaluators,
    the resulting findings list SHALL contain exactly those results where
    verdict == "fail" — no more, no fewer.
    """
    # Build a single chunk and a set of rules matching the evaluation results
    span_text = "Sample document text for compliance checking."
    span_offset = 0
    chunk = {
        "index": 0,
        "text": span_text,
        "start_offset": span_offset,
        "end_offset": span_offset + len(span_text),
    }

    # Build source_rules — one per evaluation result
    source_rules: list[dict[str, Any]] = []
    for result in eval_results:
        source_rules.append(
            {
                "id": result.rule_id,
                "description": f"Description for {result.rule_id}",
                "check_description": f"Check for {result.rule_id}",
                "scope": "source",
                "check_type": "llm",
            }
        )

    # Create a mock LLM evaluator that returns our fixed results
    mock_llm_evaluator = AsyncMock()
    mock_llm_evaluator.evaluate_batch = AsyncMock(return_value=eval_results)

    state = _make_base_state(
        source_rules=source_rules,
        chunks=[chunk],
    )

    result_state = asyncio.run(
        match_rules_against_sources(state, llm_evaluator=mock_llm_evaluator)
    )

    # Determine expected findings — exactly those with verdict == "fail"
    expected_fail_rule_ids = [
        r.rule_id for r in eval_results if r.verdict == "fail"
    ]

    source_findings = result_state["source_findings"]

    # The number of findings must equal the number of "fail" verdicts
    assert len(source_findings) == len(expected_fail_rule_ids), (
        f"Expected {len(expected_fail_rule_ids)} findings (fail verdicts), "
        f"got {len(source_findings)}"
    )

    # Every finding must have verdict == "fail"
    for finding in source_findings:
        assert finding["verdict"] == "fail", (
            f"Finding has verdict '{finding['verdict']}', expected 'fail'"
        )

    # The rule_ids in findings must match exactly the fail results
    actual_rule_ids = [f["rule_id"] for f in source_findings]
    assert sorted(actual_rule_ids) == sorted(expected_fail_rule_ids), (
        f"Finding rule_ids {actual_rule_ids} do not match expected "
        f"fail rule_ids {expected_fail_rule_ids}"
    )
