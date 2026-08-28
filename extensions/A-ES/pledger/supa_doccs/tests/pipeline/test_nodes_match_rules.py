"""Unit tests for the match_rules node.

Tests cover:
- Successful matching with verdicts produced
- Empty claims → empty verdicts (completed)
- Transient error on LLM API failure
- Permanent error on rule config issue
- That verdicts list has same length as claims list on success
- That completed_nodes includes "match_rules" on success
- That completed_nodes does NOT include "match_rules" on error
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.nodes.match_rules import (
    RuleConfigError,
    RuleMatchingService,
    match_rules,
)
from src.pipeline.state import (
    ComplianceVerdict,
    ExtractionResult,
    PipelineState,
    create_initial_state,
)


# --- Mock implementations ---


class MockRuleMatchingService:
    """Mock rule matching service that returns deterministic verdicts."""

    def __init__(
        self,
        *,
        default_verdict: str = "compliant",
        default_confidence: float = 0.9,
        should_fail: bool = False,
        fail_message: str = "LLM API timeout",
        should_raise_config_error: bool = False,
        config_error_message: str = "Rule file not found",
    ):
        self.default_verdict = default_verdict
        self.default_confidence = default_confidence
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.should_raise_config_error = should_raise_config_error
        self.config_error_message = config_error_message
        self.call_count = 0
        self.matched_claims: list[ExtractionResult] = []

    async def match(self, claim: ExtractionResult) -> ComplianceVerdict:
        self.call_count += 1
        self.matched_claims.append(claim)

        if self.should_raise_config_error:
            raise RuleConfigError(self.config_error_message)

        if self.should_fail:
            raise RuntimeError(self.fail_message)

        return ComplianceVerdict(
            claim_id=claim["claim_id"],
            verdict=self.default_verdict,
            confidence=self.default_confidence,
            needs_human_review=False,
            rule_id="rule-001",
            evidence_refs=["ref-1"],
        )


# --- Fixtures ---


@pytest.fixture
def base_state() -> PipelineState:
    """Create a pipeline state with claims ready for rule matching."""
    config = load_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=config,
    )
    state["claims"] = [
        ExtractionResult(
            claim_id="claim-1",
            claim_text="APR is 24%",
            chunk_index=0,
            start_offset=0,
            end_offset=10,
            confidence=0.85,
        ),
        ExtractionResult(
            claim_id="claim-2",
            claim_text="Processing fee is 500 PHP",
            chunk_index=0,
            start_offset=15,
            end_offset=40,
            confidence=0.90,
        ),
        ExtractionResult(
            claim_id="claim-3",
            claim_text="Loan term is 12 months",
            chunk_index=1,
            start_offset=0,
            end_offset=22,
            confidence=0.95,
        ),
    ]
    return state


@pytest.fixture
def empty_claims_state() -> PipelineState:
    """Create a pipeline state with no claims."""
    config = load_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=config,
    )
    state["claims"] = []
    return state


# --- Tests ---


@pytest.mark.anyio
async def test_successful_matching_with_verdicts(base_state: PipelineState):
    """Test successful rule matching produces verdicts for all claims."""
    service = MockRuleMatchingService(
        default_verdict="compliant", default_confidence=0.9
    )

    result = await match_rules(base_state, rule_matching_service=service)

    assert result["node_status"] == "completed"
    assert result["current_node"] == "match_rules"
    assert result["error_type"] is None
    assert result["error_detail"] is None
    assert len(result["verdicts"]) == 3

    # Check verdict content
    for i, verdict in enumerate(result["verdicts"]):
        assert verdict["claim_id"] == base_state["claims"][i]["claim_id"]
        assert verdict["verdict"] == "compliant"
        assert verdict["confidence"] == 0.9
        assert verdict["rule_id"] == "rule-001"


@pytest.mark.anyio
async def test_empty_claims_produces_empty_verdicts(empty_claims_state: PipelineState):
    """Test that empty claims list results in empty verdicts (completed, not error)."""
    service = MockRuleMatchingService()

    result = await match_rules(empty_claims_state, rule_matching_service=service)

    assert result["node_status"] == "completed"
    assert result["current_node"] == "match_rules"
    assert result["verdicts"] == []
    assert result["error_type"] is None
    assert result["error_detail"] is None
    # Service should not have been called
    assert service.call_count == 0


@pytest.mark.anyio
async def test_empty_claims_without_service_still_completes(
    empty_claims_state: PipelineState,
):
    """Test that empty claims completes even without a rule matching service."""
    result = await match_rules(empty_claims_state)

    assert result["node_status"] == "completed"
    assert result["verdicts"] == []


@pytest.mark.anyio
async def test_transient_error_on_llm_api_failure(base_state: PipelineState):
    """Test transient error when LLM API call fails."""
    service = MockRuleMatchingService(
        should_fail=True, fail_message="Connection timeout"
    )

    result = await match_rules(base_state, rule_matching_service=service)

    assert result["node_status"] == "error"
    assert result["error_type"] == "transient"
    assert "LLM API failure" in result["error_detail"]
    assert "Connection timeout" in result["error_detail"]
    assert result["current_node"] == "match_rules"


@pytest.mark.anyio
async def test_permanent_error_on_rule_config_issue(base_state: PipelineState):
    """Test permanent error when rule configuration is missing/unparseable."""
    service = MockRuleMatchingService(
        should_raise_config_error=True,
        config_error_message="Rules file not found at /etc/rules.yaml",
    )

    result = await match_rules(base_state, rule_matching_service=service)

    assert result["node_status"] == "error"
    assert result["error_type"] == "permanent"
    assert "Rule configuration error" in result["error_detail"]
    assert "Rules file not found" in result["error_detail"]
    assert result["current_node"] == "match_rules"


@pytest.mark.anyio
async def test_permanent_error_when_no_service_provided(base_state: PipelineState):
    """Test permanent error when no rule matching service is provided (config missing)."""
    result = await match_rules(base_state)

    assert result["node_status"] == "error"
    assert result["error_type"] == "permanent"
    assert "Rule configuration missing" in result["error_detail"]
    assert result["current_node"] == "match_rules"


@pytest.mark.anyio
async def test_verdicts_length_matches_claims_length(base_state: PipelineState):
    """Test that verdicts list has exactly the same length as claims list on success."""
    service = MockRuleMatchingService()

    result = await match_rules(base_state, rule_matching_service=service)

    assert len(result["verdicts"]) == len(base_state["claims"])


@pytest.mark.anyio
async def test_verdicts_claim_ids_match_input_claims(base_state: PipelineState):
    """Test that each verdict's claim_id corresponds to the input claim."""
    service = MockRuleMatchingService()

    result = await match_rules(base_state, rule_matching_service=service)

    input_claim_ids = [c["claim_id"] for c in base_state["claims"]]
    output_claim_ids = [v["claim_id"] for v in result["verdicts"]]
    assert output_claim_ids == input_claim_ids


@pytest.mark.anyio
async def test_completed_nodes_includes_match_rules_on_success(
    base_state: PipelineState,
):
    """Test that completed_nodes includes 'match_rules' on success."""
    service = MockRuleMatchingService()

    result = await match_rules(base_state, rule_matching_service=service)

    assert "match_rules" in result["completed_nodes"]


@pytest.mark.anyio
async def test_completed_nodes_includes_match_rules_on_empty_claims(
    empty_claims_state: PipelineState,
):
    """Test that completed_nodes includes 'match_rules' on empty claims success."""
    result = await match_rules(empty_claims_state)

    assert "match_rules" in result["completed_nodes"]


@pytest.mark.anyio
async def test_completed_nodes_preserves_prior(base_state: PipelineState):
    """Test that match_rules appends to existing completed_nodes list."""
    base_state["completed_nodes"] = ["ingest", "extract_text", "chunk", "embed", "extract_claims"]
    service = MockRuleMatchingService()

    result = await match_rules(base_state, rule_matching_service=service)

    assert result["completed_nodes"] == [
        "ingest", "extract_text", "chunk", "embed", "extract_claims", "match_rules"
    ]


@pytest.mark.anyio
async def test_completed_nodes_does_not_include_match_rules_on_transient_error(
    base_state: PipelineState,
):
    """Test that completed_nodes does NOT include 'match_rules' on transient error."""
    service = MockRuleMatchingService(should_fail=True)

    result = await match_rules(base_state, rule_matching_service=service)

    assert "match_rules" not in result["completed_nodes"]


@pytest.mark.anyio
async def test_completed_nodes_does_not_include_match_rules_on_permanent_error(
    base_state: PipelineState,
):
    """Test that completed_nodes does NOT include 'match_rules' on permanent error."""
    service = MockRuleMatchingService(should_raise_config_error=True)

    result = await match_rules(base_state, rule_matching_service=service)

    assert "match_rules" not in result["completed_nodes"]


@pytest.mark.anyio
async def test_completed_nodes_does_not_include_match_rules_no_service(
    base_state: PipelineState,
):
    """Test that completed_nodes does NOT include 'match_rules' when no service provided."""
    result = await match_rules(base_state)

    assert "match_rules" not in result["completed_nodes"]


@pytest.mark.anyio
async def test_single_claim_matching(base_state: PipelineState):
    """Test matching with a single claim."""
    base_state["claims"] = [
        ExtractionResult(
            claim_id="only-claim",
            claim_text="Interest rate is 18%",
            chunk_index=0,
            start_offset=0,
            end_offset=20,
            confidence=0.92,
        ),
    ]
    service = MockRuleMatchingService(
        default_verdict="non_compliant", default_confidence=0.8
    )

    result = await match_rules(base_state, rule_matching_service=service)

    assert result["node_status"] == "completed"
    assert len(result["verdicts"]) == 1
    assert result["verdicts"][0]["claim_id"] == "only-claim"
    assert result["verdicts"][0]["verdict"] == "non_compliant"
    assert result["verdicts"][0]["confidence"] == 0.8


@pytest.mark.anyio
async def test_service_called_for_each_claim(base_state: PipelineState):
    """Test that the rule matching service is called once per claim."""
    service = MockRuleMatchingService()

    await match_rules(base_state, rule_matching_service=service)

    assert service.call_count == len(base_state["claims"])
    assert len(service.matched_claims) == len(base_state["claims"])
    for i, matched_claim in enumerate(service.matched_claims):
        assert matched_claim["claim_id"] == base_state["claims"][i]["claim_id"]
