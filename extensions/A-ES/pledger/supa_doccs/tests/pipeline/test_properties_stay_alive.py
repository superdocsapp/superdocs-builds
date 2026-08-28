"""Property-based tests for Stay-Alive stage routing.

Uses Hypothesis to verify that the route_to_queue routing function
correctly determines whether to proceed to human_review or finalize
based on the escalate bucket contents.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from src.pipeline.config import load_config
from src.pipeline.routing import make_routing_fn
from src.pipeline.state import (
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


# --- Strategies ---

# Generate non-empty escalate bucket (at least 1 claim ID)
_nonempty_escalate_strategy = st.lists(
    st.uuids().map(str),
    min_size=1,
    max_size=10,
)

# Generate empty escalate bucket
_empty_escalate_strategy = st.just([])

# Generate arbitrary claim ID lists for auto_approve and auto_reject
_claim_ids_strategy = st.lists(st.uuids().map(str), max_size=10)

# Generate valid max_retries values
_max_retries_strategy = st.integers(min_value=0, max_value=10)


@st.composite
def post_route_to_queue_state_with_nonempty_escalate(
    draw: st.DrawFn,
) -> tuple[PipelineState, PipelineConfig]:
    """Generate a post-route_to_queue State with non-empty escalate bucket.

    The state represents a completed route_to_queue node where at least
    one claim was placed in the escalate bucket.
    """
    max_retries = draw(_max_retries_strategy)
    config = load_config({"max_retries": max_retries})

    state = create_initial_state(
        run_id=draw(st.uuids().map(str)),
        document_id=draw(st.uuids().map(str)),
        document_version_id=draw(st.uuids().map(str)),
        config=config,
    )

    # Set post-route_to_queue completed state
    state["node_status"] = "completed"  # type: ignore[typeddict-item]
    state["current_node"] = "route_to_queue"

    # Build queue_buckets with non-empty escalate
    state["queue_buckets"] = QueueBuckets(
        auto_approve=draw(_claim_ids_strategy),
        escalate=draw(_nonempty_escalate_strategy),
        auto_reject=draw(_claim_ids_strategy),
    )

    return state, config


@st.composite
def post_route_to_queue_state_with_empty_escalate(
    draw: st.DrawFn,
) -> tuple[PipelineState, PipelineConfig]:
    """Generate a post-route_to_queue State with empty escalate bucket.

    The state represents a completed route_to_queue node where no claims
    need human review (escalate bucket is empty).
    """
    max_retries = draw(_max_retries_strategy)
    config = load_config({"max_retries": max_retries})

    state = create_initial_state(
        run_id=draw(st.uuids().map(str)),
        document_id=draw(st.uuids().map(str)),
        document_version_id=draw(st.uuids().map(str)),
        config=config,
    )

    # Set post-route_to_queue completed state
    state["node_status"] = "completed"  # type: ignore[typeddict-item]
    state["current_node"] = "route_to_queue"

    # Build queue_buckets with empty escalate
    state["queue_buckets"] = QueueBuckets(
        auto_approve=draw(_claim_ids_strategy),
        escalate=[],
        auto_reject=draw(_claim_ids_strategy),
    )

    return state, config


# ============================================================
# Property 9: Escalate Bucket Determines Human Review Routing
# Validates: Requirements 4.5, 4.6
# ============================================================


class TestEscalateBucketRouting:
    """Property 9: Escalate Bucket Determines Human Review Routing.

    For any State returned by route_to_queue with node_status = "completed":
    - If queue_buckets["escalate"] is non-empty → routing returns "escalate"
      (routes to human_review)
    - If queue_buckets["escalate"] is empty → routing returns "next"
      (routes to finalize)

    **Validates: Requirements 4.5, 4.6**
    """

    @given(data=post_route_to_queue_state_with_nonempty_escalate())
    @settings(max_examples=200)
    def test_nonempty_escalate_routes_to_human_review(
        self, data: tuple[PipelineState, PipelineConfig]
    ) -> None:
        """Non-empty escalate bucket → routing returns 'escalate' (→ human_review)."""
        state, config = data
        route = make_routing_fn("route_to_queue", config)

        result = route(state)

        assert result == "escalate", (
            f"Expected 'escalate' when queue_buckets['escalate'] is non-empty "
            f"(has {len(state['queue_buckets']['escalate'])} items), "
            f"but got '{result}'"
        )

    @given(data=post_route_to_queue_state_with_empty_escalate())
    @settings(max_examples=200)
    def test_empty_escalate_routes_to_finalize(
        self, data: tuple[PipelineState, PipelineConfig]
    ) -> None:
        """Empty escalate bucket → routing returns 'next' (→ finalize)."""
        state, config = data
        route = make_routing_fn("route_to_queue", config)

        result = route(state)

        assert result == "next", (
            f"Expected 'next' when queue_buckets['escalate'] is empty, "
            f"but got '{result}'. "
            f"auto_approve has {len(state['queue_buckets']['auto_approve'])} items, "
            f"auto_reject has {len(state['queue_buckets']['auto_reject'])} items"
        )


# ============================================================
# Property 8: Claim Partitioning Priority
# Validates: Requirements 4.4, 4.1, 4.3
# ============================================================

import asyncio

from src.pipeline.nodes.route_to_queue import route_to_queue
from src.pipeline.state import ComplianceVerdict, ExtractionResult


# --- Strategies for Property 8 ---


@st.composite
def confidence_thresholds(draw: st.DrawFn) -> float:
    """Generate confidence threshold values between 0.01 and 0.99."""
    return draw(
        st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False)
    )


@st.composite
def verdict_types(draw: st.DrawFn) -> str:
    """Generate verdict type literals."""
    return draw(st.sampled_from(["compliant", "non_compliant", "indeterminate"]))


@st.composite
def claim_entries(draw: st.DrawFn, claim_id: str) -> ExtractionResult:
    """Generate an ExtractionResult with a specific claim_id."""
    start = draw(st.integers(min_value=0, max_value=500))
    end = draw(st.integers(min_value=start + 1, max_value=start + 500))
    return ExtractionResult(
        claim_id=claim_id,
        claim_text=draw(st.text(min_size=1, max_size=100, alphabet=st.characters(
            categories=("L", "N", "P", "Z"),
        ))),
        chunk_index=draw(st.integers(min_value=0, max_value=10)),
        start_offset=start,
        end_offset=end,
        confidence=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
    )


@st.composite
def verdict_for_claim(draw: st.DrawFn, claim_id: str) -> ComplianceVerdict:
    """Generate a ComplianceVerdict for a specific claim_id."""
    return ComplianceVerdict(
        claim_id=claim_id,
        verdict=draw(verdict_types()),
        confidence=draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)),
        needs_human_review=draw(st.booleans()),
        rule_id=draw(st.none() | st.text(min_size=1, max_size=20)),
        evidence_refs=draw(st.lists(st.text(min_size=1, max_size=20), max_size=3)),
    )


@st.composite
def claims_and_verdicts(draw: st.DrawFn) -> tuple[list[ExtractionResult], list[ComplianceVerdict], float]:
    """Generate a list of claims with corresponding verdicts and a threshold.

    Includes potential duplicates (same claim_text + chunk_index + offsets) to test auto_reject.
    """
    threshold = draw(confidence_thresholds())
    num_claims = draw(st.integers(min_value=1, max_value=10))

    claims: list[ExtractionResult] = []
    verdicts: list[ComplianceVerdict] = []

    for i in range(num_claims):
        claim_id = f"claim-{i}"

        # Decide whether to make this a duplicate of a previous claim
        is_duplicate = draw(st.booleans()) if i > 0 else False

        if is_duplicate:
            # Pick a previous claim to duplicate (same text, chunk_index, offsets)
            source_idx = draw(st.integers(min_value=0, max_value=len(claims) - 1))
            source_claim = claims[source_idx]
            claim = ExtractionResult(
                claim_id=claim_id,
                claim_text=source_claim["claim_text"],
                chunk_index=source_claim["chunk_index"],
                start_offset=source_claim["start_offset"],
                end_offset=source_claim["end_offset"],
                confidence=source_claim["confidence"],
            )
        else:
            claim = draw(claim_entries(claim_id))

        verdict = draw(verdict_for_claim(claim_id))
        claims.append(claim)
        verdicts.append(verdict)

    return claims, verdicts, threshold


def _build_route_to_queue_state(
    claims: list[ExtractionResult],
    verdicts: list[ComplianceVerdict],
    threshold: float,
) -> PipelineState:
    """Build a minimal PipelineState for route_to_queue testing."""
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

    return PipelineState(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        current_node="score_confidence",
        node_status="completed",
        error_type=None,
        error_detail=None,
        retries={},
        skipped_nodes=[],
        completed_nodes=[
            "ingest", "extract_text", "chunk", "embed",
            "extract_claims", "match_rules", "score_confidence",
        ],
        config=config,
        raw_content=None,
        mime_type=None,
        extracted_text=None,
        chunks=[],
        embeddings_stored=False,
        claims=claims,
        verdicts=verdicts,
        queue_buckets=QueueBuckets(
            auto_approve=[],
            escalate=[],
            auto_reject=[],
        ),
        decisions=[],
    )


# --- Property 8 Tests ---


class TestClaimPartitioningPriority:
    """Property 8: Claim Partitioning Priority.

    For any set of claims processed by route_to_queue:
    1. Each claim_id appears in exactly one bucket
    2. No claim_id is missing from all buckets
    3. Priority ordering holds: escalate > auto_reject > auto_approve

    **Validates: Requirements 4.4, 4.1, 4.3**
    """

    @given(data=claims_and_verdicts())
    @settings(max_examples=200)
    def test_each_claim_in_exactly_one_bucket(
        self,
        data: tuple[list[ExtractionResult], list[ComplianceVerdict], float],
    ) -> None:
        """Each claim_id appears in exactly one bucket; none missing.

        **Validates: Requirements 4.4**
        """
        claims, verdicts, threshold = data
        state = _build_route_to_queue_state(claims, verdicts, threshold)

        result_state = asyncio.run(route_to_queue(state))

        # Verify the node completed successfully
        assert result_state["node_status"] == "completed"

        buckets = result_state["queue_buckets"]
        all_claim_ids = {c["claim_id"] for c in claims}

        # Collect all claim_ids from all buckets
        auto_approve_set = set(buckets["auto_approve"])
        escalate_set = set(buckets["escalate"])
        auto_reject_set = set(buckets["auto_reject"])

        # Assert 1: Total claims in all buckets == total input claims
        total_in_buckets = (
            len(buckets["auto_approve"])
            + len(buckets["escalate"])
            + len(buckets["auto_reject"])
        )
        assert total_in_buckets == len(claims), (
            f"Expected {len(claims)} total claims in buckets, got {total_in_buckets}. "
            f"auto_approve={len(buckets['auto_approve'])}, "
            f"escalate={len(buckets['escalate'])}, "
            f"auto_reject={len(buckets['auto_reject'])}"
        )

        # Assert 2: No duplicates across buckets
        all_bucketed = auto_approve_set | escalate_set | auto_reject_set
        assert len(all_bucketed) == total_in_buckets, (
            f"Duplicate claim_ids found across buckets. "
            f"Union size={len(all_bucketed)}, total count={total_in_buckets}"
        )

        # Assert 3: No claim_id is missing from all buckets
        assert all_bucketed == all_claim_ids, (
            f"Claim IDs mismatch. Missing: {all_claim_ids - all_bucketed}. "
            f"Extra: {all_bucketed - all_claim_ids}"
        )

    @given(data=claims_and_verdicts())
    @settings(max_examples=200)
    def test_non_compliant_claims_always_escalated(
        self,
        data: tuple[list[ExtractionResult], list[ComplianceVerdict], float],
    ) -> None:
        """Non-compliant claims are always in the escalate bucket.

        **Validates: Requirements 4.4, 4.3**
        """
        claims, verdicts, threshold = data
        state = _build_route_to_queue_state(claims, verdicts, threshold)

        result_state = asyncio.run(route_to_queue(state))
        assert result_state["node_status"] == "completed"

        buckets = result_state["queue_buckets"]
        escalate_set = set(buckets["escalate"])

        # All non-compliant claims must be in the escalate bucket
        for verdict in verdicts:
            if verdict["verdict"] == "non_compliant":
                assert verdict["claim_id"] in escalate_set, (
                    f"Non-compliant claim {verdict['claim_id']} should be in "
                    f"escalate bucket but was not found there."
                )

    @given(data=claims_and_verdicts())
    @settings(max_examples=200)
    def test_low_confidence_claims_always_escalated(
        self,
        data: tuple[list[ExtractionResult], list[ComplianceVerdict], float],
    ) -> None:
        """Claims with confidence < threshold are always in escalate bucket.

        **Validates: Requirements 4.4, 4.1**
        """
        claims, verdicts, threshold = data
        state = _build_route_to_queue_state(claims, verdicts, threshold)

        result_state = asyncio.run(route_to_queue(state))
        assert result_state["node_status"] == "completed"

        buckets = result_state["queue_buckets"]
        escalate_set = set(buckets["escalate"])

        # All claims with confidence below threshold must be in escalate
        for verdict in verdicts:
            if verdict["confidence"] < threshold:
                assert verdict["claim_id"] in escalate_set, (
                    f"Claim {verdict['claim_id']} with "
                    f"confidence={verdict['confidence']} < threshold={threshold} "
                    f"should be in escalate bucket but was not found there."
                )

    @given(data=claims_and_verdicts())
    @settings(max_examples=200)
    def test_priority_escalate_over_auto_reject(
        self,
        data: tuple[list[ExtractionResult], list[ComplianceVerdict], float],
    ) -> None:
        """Priority ordering: escalate > auto_reject > auto_approve.

        **Validates: Requirements 4.4**

        If a claim qualifies for both escalate and auto_reject (e.g., it's a
        duplicate but also non-compliant or low confidence), it goes to escalate.
        """
        claims, verdicts, threshold = data
        state = _build_route_to_queue_state(claims, verdicts, threshold)

        result_state = asyncio.run(route_to_queue(state))
        assert result_state["node_status"] == "completed"

        buckets = result_state["queue_buckets"]
        escalate_set = set(buckets["escalate"])

        # Build verdict lookup
        verdict_by_id = {v["claim_id"]: v for v in verdicts}

        # For any claim that meets escalation criteria, verify it's in escalate
        for claim in claims:
            claim_id = claim["claim_id"]
            verdict = verdict_by_id.get(claim_id)
            if verdict is None:
                continue

            should_escalate = (
                verdict["verdict"] == "non_compliant"
                or verdict["confidence"] < threshold
                or verdict.get("needs_human_review", False)
            )

            if should_escalate:
                assert claim_id in escalate_set, (
                    f"Claim {claim_id} meets escalation criteria "
                    f"(verdict={verdict['verdict']}, "
                    f"confidence={verdict['confidence']}, "
                    f"needs_human_review={verdict.get('needs_human_review')}) "
                    f"but is not in escalate bucket (priority violation)."
                )


# ============================================================
# Property 15: Post-Human-Review Always Finalizes
# Validates: Requirements 5.6
# ============================================================


# --- Strategies for Property 15 ---

_decision_values = st.sampled_from(["approved", "rejected"])


@st.composite
def decision_entry(draw: st.DrawFn) -> dict:
    """Generate a single Decision entry with varied decision values."""
    from src.pipeline.state import Decision

    return Decision(
        claim_id=draw(st.uuids().map(str)),
        approval_queue_id=draw(st.uuids().map(str)),
        decision_value=draw(_decision_values),
        reviewer_id=draw(st.uuids().map(str)),
        justification=draw(st.text(min_size=0, max_size=100, alphabet=st.characters(
            categories=("L", "N", "P", "Z"),
        ))),
    )


@st.composite
def post_human_review_state(draw: st.DrawFn) -> tuple[PipelineState, PipelineConfig]:
    """Generate a post-human_review State with node_status='completed'.

    Generates varied decisions lists: empty, all approved, all rejected, or mixed.
    The routing function should ALWAYS return 'finalize' regardless of decisions content.
    """
    max_retries = draw(_max_retries_strategy)
    config = load_config({"max_retries": max_retries})

    state = create_initial_state(
        run_id=draw(st.uuids().map(str)),
        document_id=draw(st.uuids().map(str)),
        document_version_id=draw(st.uuids().map(str)),
        config=config,
    )

    # Set post-human_review completed state
    state["node_status"] = "completed"  # type: ignore[typeddict-item]
    state["current_node"] = "human_review"

    # Generate varied decisions lists (empty, all approved, all rejected, mixed)
    decisions = draw(st.lists(decision_entry(), min_size=0, max_size=10))
    state["decisions"] = decisions

    # Also vary the queue_buckets to ensure routing is independent of bucket state
    state["queue_buckets"] = QueueBuckets(
        auto_approve=draw(_claim_ids_strategy),
        escalate=draw(_claim_ids_strategy),
        auto_reject=draw(_claim_ids_strategy),
    )

    return state, config


# --- Property 15 Tests ---


class TestPostHumanReviewAlwaysFinalizes:
    """Property 15: Post-Human-Review Always Finalizes.

    For any State where current_node="human_review" and node_status="completed",
    the routing function for human_review ALWAYS returns "finalize" regardless
    of the decisions content (empty, all approved, all rejected, or mixed).

    **Validates: Requirements 5.6**
    """

    @given(data=post_human_review_state())
    @settings(max_examples=200)
    def test_post_human_review_always_routes_to_finalize(
        self, data: tuple[PipelineState, PipelineConfig]
    ) -> None:
        """After human_review completes, routing always returns 'finalize'."""
        state, config = data
        route = make_routing_fn("human_review", config)

        result = route(state)

        assert result == "finalize", (
            f"Expected 'finalize' after human_review completed, "
            f"but got '{result}'. "
            f"decisions has {len(state['decisions'])} entries, "
            f"node_status='{state['node_status']}', "
            f"current_node='{state['current_node']}'"
        )
