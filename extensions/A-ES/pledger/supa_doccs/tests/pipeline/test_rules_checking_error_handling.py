"""Unit tests for error handling paths in the rules checking stage.

Tests cover:
- Unknown playbook_id → permanent error (PlaybookLoadError)
- Invalid YAML → permanent error with validation details
- LLM API failure → transient error
- Zero applicable source rules → empty findings, "completed"
- Structured evaluator fallback to LLM with warning

Validates: Requirements 9.1, 9.2, 9.3
"""

import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.pipeline.config import load_config
from src.pipeline.evaluators import LLMEvaluator, StructuredEvaluator
from src.pipeline.findings import CitedSpan, EvaluationResult
from src.pipeline.nodes.match_rules_against_sources import match_rules_against_sources
from src.pipeline.playbook import (
    PLAYBOOK_WHITELIST,
    RULES_DIR,
    PlaybookLoadError,
    RuleDefinition,
    load_playbook,
)
from src.pipeline.state import ChunkEntry, PipelineState, create_initial_state


# --- Helpers ---


def _make_base_state() -> PipelineState:
    """Create a base pipeline state for testing."""
    config = load_config()
    return create_initial_state(
        run_id="test-error-run",
        document_id="test-error-doc",
        document_version_id="test-error-version",
        config=config,
    )


def _make_chunks() -> list[ChunkEntry]:
    """Create valid source chunks for testing."""
    return [
        ChunkEntry(
            index=0,
            text="The annual percentage rate for this loan is 24.00%.",
            start_offset=0,
            end_offset=51,
        ),
    ]


def _make_source_rules() -> list[dict]:
    """Create valid serialized source rules."""
    rules = [
        RuleDefinition(
            id="TEST-001",
            description="Test rule",
            check_description="Check something.",
            scope="source",
            check_type="llm",
        ),
    ]
    return [r.model_dump() for r in rules]


# --- Mock Evaluators ---


class FailingLLMClient:
    """Mock LLM client that always raises an exception (simulating API failure)."""

    async def chat(self, system_prompt: str, user_prompt: str) -> dict:
        raise ConnectionError("LLM API connection timed out")


class PassingLLMClient:
    """Mock LLM client that always returns 'pass' verdicts.

    Returns a dict for single-rule evaluation (called by evaluate()),
    and a list for batch evaluation (called by evaluate_batch() with >1 rules).
    """

    async def chat(self, system_prompt: str, user_prompt: str) -> dict | list[dict]:
        rule_count = user_prompt.count("Rule ID:")
        if rule_count == 0:
            rule_count = 1

        verdict = {
            "verdict": "pass",
            "cited_start": 0,
            "cited_end": 10,
            "cited_text": "compliant",
            "explanation": "Compliant.",
        }

        # Single rule → evaluate() expects a dict
        if rule_count == 1:
            return verdict

        # Batch → evaluate_batch() expects a list
        return [
            {**verdict, "rule_id": f"rule-{i}"}
            for i in range(rule_count)
        ]


class UnsupportingStructuredEvaluator(StructuredEvaluator):
    """A structured evaluator that does not support any rules."""

    def supports(self, rule: RuleDefinition) -> bool:
        return False


# --- Test 1: Unknown playbook_id → permanent error ---


@pytest.mark.anyio
async def test_unknown_playbook_id_raises_permanent_error():
    """Calling load_playbook with an unknown ID raises PlaybookLoadError.

    Validates: Requirement 9.2 (permanent error for unknown playbook_id)
    """
    with pytest.raises(PlaybookLoadError) as exc_info:
        await load_playbook("unknown_playbook_xyz")

    assert "unknown_playbook_xyz" in str(exc_info.value).lower() or "unknown" in str(
        exc_info.value
    ).lower()
    assert "Unknown playbook_id" in str(exc_info.value)


# --- Test 2: Invalid YAML → permanent error with validation details ---


@pytest.mark.anyio
async def test_invalid_yaml_raises_permanent_error_with_details():
    """Loading a playbook with invalid schema raises PlaybookLoadError with details.

    Creates a temp YAML file missing required fields and monkey-patches
    the whitelist and rules dir to point to it.

    Validates: Requirement 9.2 (permanent error for schema validation failure)
    """
    # Create invalid YAML (missing required fields like 'rules')
    invalid_playbook = {
        "playbook_id": "test_invalid",
        "name": "Invalid Playbook",
        # Missing 'rules' field entirely
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_path = Path(tmpdir) / "test_invalid.yaml"
        with open(yaml_path, "w") as f:
            yaml.dump(invalid_playbook, f)

        patched_whitelist = {**PLAYBOOK_WHITELIST, "test_invalid": "test_invalid.yaml"}

        with (
            patch("src.pipeline.playbook.PLAYBOOK_WHITELIST", patched_whitelist),
            patch("src.pipeline.playbook.RULES_DIR", Path(tmpdir)),
        ):
            with pytest.raises(PlaybookLoadError) as exc_info:
                await load_playbook("test_invalid")

            # Should contain validation details
            error_msg = str(exc_info.value)
            assert "validation failed" in error_msg.lower() or "validation" in error_msg.lower()


# --- Test 3: LLM API failure → transient error ---


@pytest.mark.anyio
async def test_llm_api_failure_produces_transient_error():
    """LLM API failure during rule evaluation produces a transient error.

    Sets up state with valid source_rules and chunks, uses a mock LLM
    evaluator that raises an exception.

    Validates: Requirement 9.1 (LLM API failure → transient error)
    """
    state = _make_base_state()
    state["source_rules"] = _make_source_rules()
    state["chunks"] = _make_chunks()

    failing_evaluator = LLMEvaluator(llm_client=FailingLLMClient())

    result = await match_rules_against_sources(
        state,
        llm_evaluator=failing_evaluator,
    )

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert result["error_detail"] is not None
    assert "LLM API failure" in result["error_detail"]


# --- Test 4: Zero applicable source rules → empty findings, "completed" ---


@pytest.mark.anyio
async def test_zero_source_rules_produces_empty_findings():
    """Empty source_rules list produces empty findings with status 'completed'.

    Validates: Requirement 9.3 (zero applicable source rules → completed)
    """
    state = _make_base_state()
    state["source_rules"] = []  # No source rules
    state["chunks"] = _make_chunks()

    result = await match_rules_against_sources(state)

    assert result["source_findings"] == []
    assert result["node_status"] == "completed"
    assert "match_rules_against_sources" in result["completed_nodes"]


# --- Test 5: Structured evaluator fallback to LLM with warning ---


@pytest.mark.anyio
async def test_structured_evaluator_fallback_to_llm_with_warning(caplog):
    """When a structured evaluator doesn't support a rule, it falls back to LLM.

    Sets up a rule with check_type="structured" and a structured evaluator
    whose supports() returns False. Verifies the LLM evaluator is used
    instead and a warning is logged.

    Validates: Requirement 5.3 (fallback to LLM with warning)
    """
    # Create a rule that requires structured evaluation
    structured_rule = RuleDefinition(
        id="STRUCT-001",
        description="A structured check rule",
        check_description="Unsupported check description for testing.",
        scope="source",
        check_type="structured",
    )

    state = _make_base_state()
    state["source_rules"] = [structured_rule.model_dump()]
    state["chunks"] = _make_chunks()

    # Structured evaluator that doesn't support the rule
    struct_mock = UnsupportingStructuredEvaluator()

    # LLM evaluator that returns "pass" (proving fallback happened)
    llm_mock = LLMEvaluator(llm_client=PassingLLMClient())

    with caplog.at_level(logging.WARNING, logger="src.pipeline.nodes.match_rules_against_sources"):
        result = await match_rules_against_sources(
            state,
            llm_evaluator=llm_mock,
            structured_evaluator=struct_mock,
        )

    # The node should complete successfully via LLM fallback
    assert result["node_status"] == "completed"

    # A warning should be logged about the fallback
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "falling back to LLM" in msg or "does not support" in msg
        for msg in warning_messages
    ), f"Expected fallback warning in logs, got: {warning_messages}"

    # No findings since mock LLM returns "pass"
    assert result["source_findings"] == []
