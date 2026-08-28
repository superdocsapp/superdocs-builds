"""Integration test: violation corpus produces exactly one finding.

Validates Requirement 8.2 — when the match_rules_against_sources node is run
against a violation test corpus containing exactly one known violation, it
returns exactly one Finding with the correct rule_id and a cited_span that
matches the violation location.

Setup:
- Playbook with 3 known rules (MF-001, MF-002, MF-003)
- Source span containing a single violation ("annual interest rate of 42.00%")
- Mock LLM evaluator returning "fail" for MF-001, "pass" for all others
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.findings import CitedSpan, EvaluationResult
from src.pipeline.nodes.match_rules_against_sources import match_rules_against_sources
from src.pipeline.playbook import RuleDefinition
from src.pipeline.state import ChunkEntry, PipelineState, create_initial_state


# --- Constants for test corpus ---

# The source span text with a known violation at a specific offset
VIOLATION_SPAN_TEXT = (
    "The borrower agrees to the following terms: "
    "annual interest rate of 42.00% applied monthly."
)

# The violation substring and its offsets within the span
VIOLATION_TEXT = "annual interest rate of 42.00%"
VIOLATION_START_IN_SPAN = VIOLATION_SPAN_TEXT.index(VIOLATION_TEXT)
VIOLATION_END_IN_SPAN = VIOLATION_START_IN_SPAN + len(VIOLATION_TEXT)

# The span offset in the original document
SPAN_OFFSET = 100

# Absolute offsets in the document (span_offset + relative offset)
VIOLATION_START_ABSOLUTE = SPAN_OFFSET + VIOLATION_START_IN_SPAN
VIOLATION_END_ABSOLUTE = SPAN_OFFSET + VIOLATION_END_IN_SPAN


# --- Source rules (serialized RuleDefinition dicts) ---

SOURCE_RULES = [
    {
        "id": "MF-001",
        "description": "APR must not exceed 36%",
        "check_description": "Check if the stated annual percentage rate (APR) exceeds 36%.",
        "scope": "source",
        "check_type": "llm",
    },
    {
        "id": "MF-002",
        "description": "Processing fee must be disclosed",
        "check_description": "Verify that a processing fee amount is explicitly stated.",
        "scope": "source",
        "check_type": "llm",
    },
    {
        "id": "MF-003",
        "description": "Repayment schedule must be present",
        "check_description": "Check that the document contains a repayment schedule.",
        "scope": "source",
        "check_type": "llm",
    },
]


# --- Mock LLM Evaluator ---


class MockLLMEvaluator:
    """Mock LLM evaluator that returns 'fail' for MF-001 and 'pass' for others.

    Simulates an LLM that detects the APR violation in the span and
    returns the correct cited_span pointing to the violation location.
    """

    def __init__(self) -> None:
        self.evaluate_batch_call_count = 0

    async def evaluate_batch(
        self,
        rules: list[RuleDefinition],
        span_text: str,
        span_offset: int,
    ) -> list[EvaluationResult]:
        """Return deterministic results: fail for MF-001, pass for others."""
        self.evaluate_batch_call_count += 1
        results: list[EvaluationResult] = []

        for rule in rules:
            if rule.id == "MF-001":
                # This rule detects the violation
                results.append(
                    EvaluationResult(
                        rule_id=rule.id,
                        verdict="fail",
                        cited_span=CitedSpan(
                            start_offset=span_offset + VIOLATION_START_IN_SPAN,
                            end_offset=span_offset + VIOLATION_END_IN_SPAN,
                            text=VIOLATION_TEXT,
                        ),
                        explanation="The stated APR of 42% exceeds the 36% regulatory maximum.",
                        evaluation_method="llm",
                    )
                )
            else:
                # All other rules pass
                results.append(
                    EvaluationResult(
                        rule_id=rule.id,
                        verdict="pass",
                        cited_span=CitedSpan(
                            start_offset=span_offset,
                            end_offset=span_offset + len(span_text),
                            text=span_text,
                        ),
                        explanation=f"Rule {rule.id} is satisfied.",
                        evaluation_method="llm",
                    )
                )

        return results

    async def evaluate(
        self,
        rule: RuleDefinition,
        span_text: str,
        span_offset: int,
    ) -> EvaluationResult:
        """Single-rule evaluation (delegates to batch with one rule)."""
        results = await self.evaluate_batch([rule], span_text, span_offset)
        return results[0]


# --- Fixtures ---


@pytest.fixture
def violation_state() -> PipelineState:
    """Create a pipeline state with source rules and a chunk containing a violation."""
    config = load_config()
    state = create_initial_state(
        run_id="test-violation-run",
        document_id="test-violation-doc",
        document_version_id="test-violation-version",
        config=config,
    )
    state["source_rules"] = SOURCE_RULES
    state["chunks"] = [
        ChunkEntry(
            index=0,
            text=VIOLATION_SPAN_TEXT,
            start_offset=SPAN_OFFSET,
            end_offset=SPAN_OFFSET + len(VIOLATION_SPAN_TEXT),
        ),
    ]
    return state


# --- Integration Tests ---


@pytest.mark.anyio
async def test_violation_corpus_produces_one_finding(violation_state: PipelineState):
    """Run match_rules_against_sources against a corpus with one violation.

    Setup:
    - Load a playbook with known rules
    - Provide source spans containing exactly one rule violation at a known offset
    - Use a mock LLM that returns "fail" for the violating rule and "pass" for others

    Assert:
    - findings list has exactly 1 entry
    - finding.rule_id matches the violated rule
    - finding.cited_span.start_offset and end_offset match the violation location
    - finding.evaluation_method is correct
    """
    mock_evaluator = MockLLMEvaluator()

    result = await match_rules_against_sources(
        violation_state, llm_evaluator=mock_evaluator
    )

    # Node should complete successfully
    assert result["node_status"] == "completed"

    # Exactly 1 finding (only MF-001 fails)
    assert len(result["source_findings"]) == 1

    finding = result["source_findings"][0]

    # Correct rule_id
    assert finding["rule_id"] == "MF-001"

    # Correct verdict
    assert finding["verdict"] == "fail"

    # Cited span offsets match the known violation location
    assert finding["cited_span"]["start_offset"] == VIOLATION_START_ABSOLUTE
    assert finding["cited_span"]["end_offset"] == VIOLATION_END_ABSOLUTE
    assert finding["cited_span"]["text"] == VIOLATION_TEXT

    # Correct evaluation method
    assert finding["evaluation_method"] == "llm"


@pytest.mark.anyio
async def test_violation_corpus_evaluator_called(violation_state: PipelineState):
    """Verify the mock evaluator's evaluate_batch is actually invoked."""
    mock_evaluator = MockLLMEvaluator()

    await match_rules_against_sources(violation_state, llm_evaluator=mock_evaluator)

    # evaluate_batch should have been called once (one chunk, batched rules)
    assert mock_evaluator.evaluate_batch_call_count == 1


@pytest.mark.anyio
async def test_violation_corpus_completed_nodes(violation_state: PipelineState):
    """Verify match_rules_against_sources is added to completed_nodes."""
    mock_evaluator = MockLLMEvaluator()

    result = await match_rules_against_sources(
        violation_state, llm_evaluator=mock_evaluator
    )

    assert "match_rules_against_sources" in result["completed_nodes"]
