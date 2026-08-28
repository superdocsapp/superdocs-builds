"""Property-based tests for Finding structural completeness.

**Validates: Requirements 6.4, 6.5, 3.4**

Property 7: Finding Structural Completeness
For any Finding produced by the node, it SHALL contain all required fields
with valid values: rule_id (non-empty string), verdict (literal "fail"),
cited_span with start_offset < end_offset and non-empty text, explanation
(non-empty string), and evaluation_method (one of "llm" or "structured").
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.findings import CitedSpan, EvaluationMethod, Finding


# --- Strategies ---


@st.composite
def valid_cited_spans(draw: st.DrawFn) -> CitedSpan:
    """Generate valid CitedSpan instances where start < end and text is non-empty."""
    start = draw(st.integers(min_value=0, max_value=100_000))
    end = draw(st.integers(min_value=start + 1, max_value=start + 10_000))
    text = draw(st.text(min_size=1, max_size=500, alphabet=st.characters(
        categories=("L", "N", "P", "Z", "S"),
    )))
    return CitedSpan(start_offset=start, end_offset=end, text=text)


@st.composite
def valid_evaluation_methods(draw: st.DrawFn) -> EvaluationMethod:
    """Generate valid evaluation method values."""
    return draw(st.sampled_from(["llm", "structured"]))


@st.composite
def valid_findings(draw: st.DrawFn) -> Finding:
    """Generate valid Finding instances with all structural constraints satisfied."""
    rule_id = draw(st.text(min_size=1, max_size=100, alphabet=st.characters(
        categories=("L", "N", "P", "S"),
    )))
    cited_span = draw(valid_cited_spans())
    explanation = draw(st.text(min_size=1, max_size=500, alphabet=st.characters(
        categories=("L", "N", "P", "Z", "S"),
    )))
    evaluation_method = draw(valid_evaluation_methods())

    return Finding(
        rule_id=rule_id,
        verdict="fail",
        cited_span=cited_span,
        explanation=explanation,
        evaluation_method=evaluation_method,
    )


# --- Property Tests ---


@given(finding=valid_findings())
@settings(max_examples=200)
def test_finding_structural_completeness(finding: Finding) -> None:
    """Property 7: Finding Structural Completeness.

    **Validates: Requirements 6.4, 6.5, 3.4**

    Every Finding has non-empty rule_id, verdict=="fail", valid cited_span
    (start < end, non-empty text), non-empty explanation, and valid
    evaluation_method.
    """
    # rule_id is non-empty string
    assert isinstance(finding.rule_id, str), (
        f"rule_id must be a string, got {type(finding.rule_id)}"
    )
    assert len(finding.rule_id) > 0, "rule_id must be non-empty"

    # verdict is always "fail"
    assert finding.verdict == "fail", (
        f"verdict must be 'fail', got '{finding.verdict}'"
    )

    # cited_span.start_offset < cited_span.end_offset
    assert finding.cited_span.start_offset < finding.cited_span.end_offset, (
        f"cited_span.start_offset ({finding.cited_span.start_offset}) must be < "
        f"cited_span.end_offset ({finding.cited_span.end_offset})"
    )

    # cited_span.text is non-empty
    assert isinstance(finding.cited_span.text, str), (
        f"cited_span.text must be a string, got {type(finding.cited_span.text)}"
    )
    assert len(finding.cited_span.text) > 0, "cited_span.text must be non-empty"

    # explanation is non-empty string
    assert isinstance(finding.explanation, str), (
        f"explanation must be a string, got {type(finding.explanation)}"
    )
    assert len(finding.explanation) > 0, "explanation must be non-empty"

    # evaluation_method is one of "llm" or "structured"
    assert finding.evaluation_method in ("llm", "structured"), (
        f"evaluation_method must be 'llm' or 'structured', "
        f"got '{finding.evaluation_method}'"
    )
