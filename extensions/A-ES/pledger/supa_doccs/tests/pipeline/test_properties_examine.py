"""Property-based tests for Examine Stage — extraction offset ordering.

**Validates: Requirements 9.1**

Property 12: Extraction Offset Ordering
For any ExtractionResult produced by the extract_claims node,
start_offset < end_offset and both offsets are within the bounds of
the chunk text (0 <= start_offset < end_offset <= len(chunk_text)).
"""

from __future__ import annotations

import asyncio
from typing import List

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.nodes.extract_claims import ClaimExtractor, extract_claims
from src.pipeline.state import (
    ChunkEntry,
    ExtractionResult,
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


# --- Strategies ---


@st.composite
def chunk_texts(draw: st.DrawFn) -> str:
    """Generate chunk texts of varying lengths."""
    return draw(st.text(min_size=1, max_size=1000, alphabet=st.characters(
        categories=("L", "N", "P", "Z", "S"),
    )))


@st.composite
def valid_offset_pairs(draw: st.DrawFn, text_length: int) -> tuple[int, int]:
    """Generate valid offset pairs within chunk text bounds (start < end)."""
    start = draw(st.integers(min_value=0, max_value=text_length - 1))
    end = draw(st.integers(min_value=start + 1, max_value=text_length))
    return (start, end)


@st.composite
def extraction_results_for_chunk(
    draw: st.DrawFn, chunk_text: str, chunk_index: int
) -> ExtractionResult:
    """Generate ExtractionResult entries with offsets within chunk text bounds."""
    text_length = len(chunk_text)
    start, end = draw(valid_offset_pairs(text_length))
    claim_text = chunk_text[start:end]

    return ExtractionResult(
        claim_id=draw(st.uuids().map(str)),
        claim_text=claim_text if claim_text else "claim",
        chunk_index=chunk_index,
        start_offset=start,
        end_offset=end,
        confidence=draw(st.floats(min_value=0.0, max_value=1.0)),
    )


@st.composite
def chunk_with_extraction_results(
    draw: st.DrawFn,
) -> tuple[str, int, list[ExtractionResult]]:
    """Generate a chunk text and associated ExtractionResult entries."""
    text = draw(chunk_texts())
    chunk_index = draw(st.integers(min_value=0, max_value=50))
    num_results = draw(st.integers(min_value=1, max_value=5))

    results = [
        draw(extraction_results_for_chunk(text, chunk_index))
        for _ in range(num_results)
    ]
    return (text, chunk_index, results)


# --- Property Tests ---


@given(data=chunk_with_extraction_results())
@settings(max_examples=200)
def test_extraction_offset_ordering_structural(
    data: tuple[str, int, list[ExtractionResult]],
) -> None:
    """Property 12: Extraction Offset Ordering (structural validation).

    **Validates: Requirements 9.1**

    For any ExtractionResult, start_offset < end_offset and both offsets
    are within the bounds of the chunk text:
    0 <= start_offset < end_offset <= len(chunk_text).
    """
    chunk_text, _chunk_index, results = data

    for result in results:
        # start_offset must be strictly less than end_offset
        assert result["start_offset"] < result["end_offset"], (
            f"start_offset ({result['start_offset']}) must be < "
            f"end_offset ({result['end_offset']})"
        )
        # start_offset must be >= 0
        assert result["start_offset"] >= 0, (
            f"start_offset ({result['start_offset']}) must be >= 0"
        )
        # end_offset must be <= len(chunk_text)
        assert result["end_offset"] <= len(chunk_text), (
            f"end_offset ({result['end_offset']}) must be <= "
            f"len(chunk_text) ({len(chunk_text)})"
        )


@given(data=chunk_with_extraction_results())
@settings(max_examples=200)
def test_extraction_offset_ordering_integration(
    data: tuple[str, int, list[ExtractionResult]],
) -> None:
    """Property 12: Extraction Offset Ordering (extract_claims integration).

    **Validates: Requirements 9.1**

    Generate chunks with known text, use a mock ClaimExtractor that produces
    ExtractionResults, and verify all results satisfy start_offset < end_offset
    and offsets are within chunk text bounds.
    """
    chunk_text, chunk_index, expected_results = data

    class MockClaimExtractor:
        """Mock extractor that returns pre-generated ExtractionResults."""

        async def extract(
            self, text: str, index: int
        ) -> List[ExtractionResult]:
            return expected_results

    # Build a minimal pipeline state with the chunk
    config = PipelineConfig(
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

    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=config,
    )

    # Add the chunk to state
    chunk_entry = ChunkEntry(
        index=chunk_index,
        text=chunk_text,
        start_offset=0,
        end_offset=len(chunk_text),
    )
    state = PipelineState(**{**state, "chunks": [chunk_entry]})

    # Run the extract_claims node with mock extractor
    result_state = asyncio.run(
        extract_claims(state, extractor=MockClaimExtractor())
    )

    # Verify all claims satisfy offset ordering
    assert result_state["node_status"] == "completed"
    for claim in result_state["claims"]:
        # start_offset must be strictly less than end_offset
        assert claim["start_offset"] < claim["end_offset"], (
            f"start_offset ({claim['start_offset']}) must be < "
            f"end_offset ({claim['end_offset']})"
        )
        # start_offset must be >= 0
        assert claim["start_offset"] >= 0, (
            f"start_offset ({claim['start_offset']}) must be >= 0"
        )
        # end_offset must be <= len(chunk_text)
        assert claim["end_offset"] <= len(chunk_text), (
            f"end_offset ({claim['end_offset']}) must be <= "
            f"len(chunk_text) ({len(chunk_text)})"
        )


# =============================================================================
# Property 13: Verdicts-Claims Length Parity
# =============================================================================

from src.pipeline.nodes.match_rules import RuleMatchingService, match_rules
from src.pipeline.state import ComplianceVerdict


# --- Mock RuleMatchingService ---


class DeterministicRuleMatchingService:
    """A mock RuleMatchingService that produces deterministic verdicts for each claim."""

    async def match(self, claim: ExtractionResult) -> ComplianceVerdict:
        """Produce a deterministic ComplianceVerdict based on the claim's data."""
        return ComplianceVerdict(
            claim_id=claim["claim_id"],
            verdict="compliant",
            confidence=0.85,
            needs_human_review=False,
            rule_id="rule-001",
            evidence_refs=[],
        )


# --- Strategies for Property 13 ---


@st.composite
def extraction_results_for_match(draw: st.DrawFn) -> ExtractionResult:
    """Generate valid ExtractionResult instances for match_rules testing."""
    start = draw(st.integers(min_value=0, max_value=10000))
    end = draw(st.integers(min_value=start + 1, max_value=start + 1000))
    return ExtractionResult(
        claim_id=draw(st.uuids().map(str)),
        claim_text=draw(st.text(min_size=1, max_size=200)),
        chunk_index=draw(st.integers(min_value=0, max_value=50)),
        start_offset=start,
        end_offset=end,
        confidence=draw(st.floats(min_value=0.0, max_value=1.0)),
    )


# --- Property Test ---


@given(claims=st.lists(extraction_results_for_match(), min_size=1, max_size=20))
@settings(max_examples=200)
def test_verdicts_claims_length_parity(claims: list[ExtractionResult]) -> None:
    """Property 13: Verdicts-Claims Length Parity.

    **Validates: Requirements 9.2**

    For any non-empty claims list processed by the match_rules node, the resulting
    verdicts list has exactly the same length as the claims list, and each verdict's
    claim_id corresponds 1:1 to the input claim at the same index.
    """
    # Build a minimal PipelineState with the generated claims
    config = PipelineConfig(
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

    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-doc-version-id",
        config=config,
    )
    # Inject the generated claims into the state
    state = PipelineState(**{**state, "claims": claims})

    # Run match_rules with our deterministic mock service
    service = DeterministicRuleMatchingService()
    result = asyncio.run(match_rules(state, rule_matching_service=service))

    # Assert 1: verdicts list has exactly the same length as claims list
    assert len(result["verdicts"]) == len(claims), (
        f"Expected {len(claims)} verdicts, got {len(result['verdicts'])}"
    )

    # Assert 2: Each verdict's claim_id corresponds 1:1 to the input claim at same index
    for i, (verdict, claim) in enumerate(zip(result["verdicts"], claims)):
        assert verdict["claim_id"] == claim["claim_id"], (
            f"Verdict at index {i} has claim_id={verdict['claim_id']}, "
            f"expected {claim['claim_id']}"
        )


# --- Property 14: Confidence Flagging Threshold ---


from src.pipeline.nodes.score_confidence import score_confidence
from src.pipeline.state import ComplianceVerdict


@st.composite
def confidence_thresholds(draw: st.DrawFn) -> float:
    """Generate confidence threshold values between 0.0 and 1.0."""
    return draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))


@st.composite
def confidence_values(draw: st.DrawFn) -> float:
    """Generate confidence values between 0.0 and 1.0."""
    return draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))


@st.composite
def verdict_types(draw: st.DrawFn) -> str:
    """Generate verdict type literals."""
    return draw(st.sampled_from(["compliant", "non_compliant", "indeterminate"]))


@st.composite
def compliance_verdicts_for_scoring(draw: st.DrawFn) -> ComplianceVerdict:
    """Generate ComplianceVerdict instances for confidence scoring tests."""
    return ComplianceVerdict(
        claim_id=draw(st.uuids().map(str)),
        verdict=draw(verdict_types()),
        confidence=draw(confidence_values()),
        needs_human_review=draw(st.booleans()),  # will be overwritten by score_confidence
        rule_id=draw(st.none() | st.text(min_size=1, max_size=50)),
        evidence_refs=draw(st.lists(st.text(min_size=1, max_size=50), max_size=3)),
    )


def _build_state_with_verdicts(
    verdicts: list[ComplianceVerdict], config: PipelineConfig
) -> PipelineState:
    """Build a minimal PipelineState with given verdicts and config."""
    return PipelineState(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        current_node="match_rules",
        node_status="completed",
        error_type=None,
        error_detail=None,
        retries={},
        skipped_nodes=[],
        completed_nodes=["ingest", "extract_text", "chunk", "embed", "extract_claims", "match_rules"],
        config=config,
        raw_content=None,
        mime_type=None,
        extracted_text=None,
        chunks=[],
        embeddings_stored=False,
        claims=[],
        verdicts=verdicts,
        queue_buckets=QueueBuckets(
            auto_approve=[],
            escalate=[],
            auto_reject=[],
        ),
        decisions=[],
    )


@given(
    threshold=confidence_thresholds(),
    verdicts=st.lists(compliance_verdicts_for_scoring(), min_size=1, max_size=10),
)
@settings(max_examples=200)
def test_confidence_flagging_threshold(
    threshold: float,
    verdicts: list[ComplianceVerdict],
) -> None:
    """Property 14: Confidence Flagging Threshold.

    **Validates: Requirements 9.3, 4.1**

    For any verdict processed by the score_confidence node:
    - If verdict == "non_compliant": needs_human_review is ALWAYS True
    - If verdict != "non_compliant" and confidence < threshold: needs_human_review is True
    - If verdict != "non_compliant" and confidence >= threshold: needs_human_review is False
    """
    config = PipelineConfig(
        max_retries=3,
        chunk_max_size=1000,
        chunk_overlap=200,
        confidence_threshold=threshold,
        review_timeout_hours=72,
        reminder_interval_hours=24,
        poll_interval_seconds=30,
        extract_text_timeout_seconds=60,
        min_chunk_threshold=200,
    )

    state = _build_state_with_verdicts(verdicts, config)

    # Run the score_confidence node (no scoring service — just threshold flagging)
    result_state = asyncio.run(score_confidence(state))

    # Verify the node completed successfully
    assert result_state["node_status"] == "completed"
    assert result_state["current_node"] == "score_confidence"

    result_verdicts = result_state["verdicts"]
    assert len(result_verdicts) == len(verdicts)

    for i, result_verdict in enumerate(result_verdicts):
        original_verdict = verdicts[i]
        verdict_type = original_verdict["verdict"]
        confidence = original_verdict["confidence"]

        if verdict_type == "non_compliant":
            # Non-compliant verdicts ALWAYS need human review
            assert result_verdict["needs_human_review"] is True, (
                f"Verdict {i}: non_compliant with confidence={confidence} "
                f"should always have needs_human_review=True, "
                f"but got {result_verdict['needs_human_review']}"
            )
        elif confidence < threshold:
            # Below threshold → needs human review
            assert result_verdict["needs_human_review"] is True, (
                f"Verdict {i}: {verdict_type} with confidence={confidence} < threshold={threshold} "
                f"should have needs_human_review=True, "
                f"but got {result_verdict['needs_human_review']}"
            )
        else:
            # At or above threshold and not non-compliant → no human review needed
            assert result_verdict["needs_human_review"] is False, (
                f"Verdict {i}: {verdict_type} with confidence={confidence} >= threshold={threshold} "
                f"should have needs_human_review=False, "
                f"but got {result_verdict['needs_human_review']}"
            )
