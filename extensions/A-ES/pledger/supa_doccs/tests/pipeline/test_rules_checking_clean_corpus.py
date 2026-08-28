"""Integration test: clean corpus produces no findings.

Runs match_rules_against_sources against a compliant document corpus
with a mock LLM that returns "pass" for all evaluations. Verifies that
the node produces zero findings and completes successfully.

Validates: Requirement 8.1
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.evaluators import LLMEvaluator
from src.pipeline.findings import CitedSpan, EvaluationResult
from src.pipeline.nodes.match_rules_against_sources import match_rules_against_sources
from src.pipeline.playbook import RuleDefinition
from src.pipeline.state import ChunkEntry, PipelineState, create_initial_state


# --- Mock LLM Client ---


class PassingLLMClient:
    """Mock LLM client that always returns 'pass' verdicts.

    Simulates a clean corpus where no rules are violated.
    """

    async def chat(self, system_prompt: str, user_prompt: str) -> list[dict]:
        """Return 'pass' verdict for every rule in a batch request.

        Parses the user prompt to determine how many rules are being evaluated
        and returns a 'pass' verdict for each one.
        """
        # Count rules by looking for "Rule ID:" occurrences in the prompt
        rule_count = user_prompt.count("Rule ID:")
        if rule_count == 0:
            rule_count = 1

        return [
            {
                "rule_id": f"rule-{i}",
                "verdict": "pass",
                "cited_start": 0,
                "cited_end": 10,
                "cited_text": "compliant",
                "explanation": "The document complies with this rule.",
            }
            for i in range(rule_count)
        ]


# --- Test Data ---


def _make_source_rules() -> list[dict]:
    """Create serialized source rules for a compliant document evaluation."""
    rules = [
        RuleDefinition(
            id="MF-001",
            description="APR must not exceed 36%",
            check_description="Check if the stated APR exceeds 36%.",
            scope="source",
            check_type="llm",
        ),
        RuleDefinition(
            id="MF-002",
            description="Processing fee must be disclosed",
            check_description="Verify that a processing fee amount is explicitly stated.",
            scope="source",
            check_type="llm",
        ),
        RuleDefinition(
            id="MF-003",
            description="Repayment schedule must be present",
            check_description="Check that the document contains a repayment schedule.",
            scope="source",
            check_type="llm",
        ),
    ]
    return [r.model_dump() for r in rules]


def _make_compliant_chunks() -> list[ChunkEntry]:
    """Create source spans from a compliant document (no violations)."""
    return [
        ChunkEntry(
            index=0,
            text=(
                "The annual percentage rate (APR) for this loan is 24.00%. "
                "A processing fee of PHP 500.00 is charged at disbursement."
            ),
            start_offset=0,
            end_offset=120,
        ),
        ChunkEntry(
            index=1,
            text=(
                "Repayment schedule: 12 monthly installments of PHP 4,750.00 "
                "beginning on 2024-02-01. Total repayment amount: PHP 57,000.00."
            ),
            start_offset=120,
            end_offset=240,
        ),
        ChunkEntry(
            index=2,
            text=(
                "The borrower acknowledges receipt of the loan disclosure statement "
                "and agrees to the terms and conditions outlined herein."
            ),
            start_offset=240,
            end_offset=360,
        ),
    ]


# --- Fixtures ---


@pytest.fixture
def clean_corpus_state() -> PipelineState:
    """Create a pipeline state representing a compliant document."""
    config = load_config()
    state = create_initial_state(
        run_id="test-clean-run",
        document_id="test-clean-doc",
        document_version_id="test-clean-version",
        config=config,
    )
    state["source_rules"] = _make_source_rules()
    state["chunks"] = _make_compliant_chunks()
    return state


@pytest.fixture
def mock_llm_evaluator() -> LLMEvaluator:
    """Create an LLMEvaluator with a mock client that always returns 'pass'."""
    return LLMEvaluator(llm_client=PassingLLMClient())


# --- Tests ---


@pytest.mark.anyio
async def test_clean_corpus_produces_no_findings(
    clean_corpus_state: PipelineState,
    mock_llm_evaluator: LLMEvaluator,
):
    """Run match_rules_against_sources against a clean corpus.

    Setup:
    - Load a playbook with known rules (3 source-scoped rules)
    - Provide source spans from a document that complies with all rules
    - Use a mock LLM that returns "pass" for all evaluations

    Assert:
    - findings list is empty
    - node_status is "completed"
    - "match_rules_against_sources" is in completed_nodes
    """
    result = await match_rules_against_sources(
        clean_corpus_state,
        llm_evaluator=mock_llm_evaluator,
    )

    assert result["source_findings"] == []
    assert result["node_status"] == "completed"
    assert "match_rules_against_sources" in result["completed_nodes"]


@pytest.mark.anyio
async def test_clean_corpus_no_error_state(
    clean_corpus_state: PipelineState,
    mock_llm_evaluator: LLMEvaluator,
):
    """Verify that a clean corpus run does not set any error fields."""
    result = await match_rules_against_sources(
        clean_corpus_state,
        llm_evaluator=mock_llm_evaluator,
    )

    assert result["error_type"] is None
    assert result["error_detail"] is None


@pytest.mark.anyio
async def test_clean_corpus_current_node_is_set(
    clean_corpus_state: PipelineState,
    mock_llm_evaluator: LLMEvaluator,
):
    """Verify that current_node is set to match_rules_against_sources after run."""
    result = await match_rules_against_sources(
        clean_corpus_state,
        llm_evaluator=mock_llm_evaluator,
    )

    assert result["current_node"] == "match_rules_against_sources"
