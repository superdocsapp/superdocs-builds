"""Unit tests for the routing function factory and per-node routing logic.

Tests cover all routing conditions from the requirements routing table:
- Each node's completed → next routing
- Skip logic for extract_text and chunk
- Retry below max → retry
- Retry at max → escalate
- Permanent error → escalate
- Unhandled state → escalate
- route_to_queue escalate bucket logic
- human_review always → finalize
- finalize end/retry/escalate
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.routing import make_routing_fn
from src.pipeline.state import (
    PipelineConfig,
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


@pytest.fixture
def config() -> PipelineConfig:
    """Default pipeline configuration for tests."""
    return load_config()


def _make_state(
    node_status: str = "completed",
    error_type: str | None = None,
    error_detail: str | None = None,
    retries: dict[str, int] | None = None,
    queue_buckets: QueueBuckets | None = None,
) -> PipelineState:
    """Create a minimal PipelineState for routing tests."""
    cfg = load_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=cfg,
    )
    state["node_status"] = node_status  # type: ignore[typeddict-item]
    state["error_type"] = error_type  # type: ignore[typeddict-item]
    state["error_detail"] = error_detail
    if retries is not None:
        state["retries"] = retries
    if queue_buckets is not None:
        state["queue_buckets"] = queue_buckets
    return state


# ============================================================
# ingest: next / escalate (no retry, no skip)
# ============================================================


class TestIngestRouting:
    """Tests for ingest node routing (next/escalate only)."""

    def test_completed_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("ingest", config)
        state = _make_state(node_status="completed")
        assert route(state) == "next"

    def test_permanent_error_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("ingest", config)
        state = _make_state(node_status="error", error_type="permanent")
        assert route(state) == "escalate"

    def test_transient_error_returns_escalate(self, config: PipelineConfig) -> None:
        """Ingest has no retry support — even transient errors escalate."""
        route = make_routing_fn("ingest", config)
        state = _make_state(
            node_status="error", error_type="transient", retries={"ingest": 0}
        )
        assert route(state) == "escalate"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("ingest", config)
        state = _make_state(node_status="something_weird")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# extract_text: next / retry / escalate
# ============================================================


class TestExtractTextRouting:
    """Tests for extract_text node routing."""

    def test_completed_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("extract_text", config)
        state = _make_state(node_status="completed")
        assert route(state) == "next"

    def test_skipped_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("extract_text", config)
        state = _make_state(node_status="skipped")
        state["skipped_nodes"] = [{"node_name": "extract_text", "reason": "input_already_text"}]
        assert route(state) == "next"

    def test_transient_error_below_max_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("extract_text", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"extract_text": 2},  # max is 3, so 2 < 3 → retry
        )
        assert route(state) == "retry"

    def test_transient_error_at_max_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("extract_text", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"extract_text": 3},  # max is 3, so 3 >= 3 → escalate
        )
        assert route(state) == "escalate"

    def test_permanent_error_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("extract_text", config)
        state = _make_state(node_status="error", error_type="permanent")
        assert route(state) == "escalate"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("extract_text", config)
        state = _make_state(node_status="unknown_status")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# classify_document: next / retry / escalate (with unclassified check)
# ============================================================


class TestClassifyDocumentRouting:
    """Tests for classify_document node routing."""

    def test_completed_classified_returns_next(self, config: PipelineConfig) -> None:
        """Completed with a valid classification label → next (chunk)."""
        route = make_routing_fn("classify_document", config)
        state = _make_state(node_status="completed")
        state["classification_label"] = "loan_agreement"  # type: ignore[typeddict-item]
        assert route(state) == "next"

    def test_completed_unclassified_returns_escalate(self, config: PipelineConfig) -> None:
        """Completed with 'unclassified' label → escalate (route_to_queue)."""
        route = make_routing_fn("classify_document", config)
        state = _make_state(node_status="completed")
        state["classification_label"] = "unclassified"  # type: ignore[typeddict-item]
        assert route(state) == "escalate"

    def test_transient_error_below_max_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("classify_document", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"classify_document": 2},  # max is 3, so 2 < 3 → retry
        )
        assert route(state) == "retry"

    def test_transient_error_at_max_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("classify_document", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"classify_document": 3},  # max is 3, so 3 >= 3 → escalate
        )
        assert route(state) == "escalate"

    def test_permanent_error_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("classify_document", config)
        state = _make_state(node_status="error", error_type="permanent")
        assert route(state) == "escalate"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("classify_document", config)
        state = _make_state(node_status="something_weird")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# chunk: next only (completed/skipped → next, error → escalate)
# ============================================================


class TestChunkRouting:
    """Tests for chunk node routing (no retry support)."""

    def test_completed_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("chunk", config)
        state = _make_state(node_status="completed")
        assert route(state) == "next"

    def test_skipped_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("chunk", config)
        state = _make_state(node_status="skipped")
        state["skipped_nodes"] = [{"node_name": "chunk", "reason": "below_chunk_threshold"}]
        assert route(state) == "next"

    def test_error_returns_escalate(self, config: PipelineConfig) -> None:
        """Chunk errors are permanent — no retry."""
        route = make_routing_fn("chunk", config)
        state = _make_state(node_status="error", error_type="permanent")
        assert route(state) == "escalate"

    def test_transient_error_still_escalates(self, config: PipelineConfig) -> None:
        """Chunk doesn't support retry even for transient errors."""
        route = make_routing_fn("chunk", config)
        state = _make_state(
            node_status="error", error_type="transient", retries={"chunk": 0}
        )
        assert route(state) == "escalate"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("chunk", config)
        state = _make_state(node_status="bogus")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# embed: next / retry / escalate
# ============================================================


class TestEmbedRouting:
    """Tests for embed node routing."""

    def test_completed_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("embed", config)
        state = _make_state(node_status="completed")
        assert route(state) == "next"

    def test_transient_error_below_max_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("embed", config)
        state = _make_state(
            node_status="error", error_type="transient", retries={"embed": 1}
        )
        assert route(state) == "retry"

    def test_transient_error_at_max_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("embed", config)
        state = _make_state(
            node_status="error", error_type="transient", retries={"embed": 3}
        )
        assert route(state) == "escalate"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("embed", config)
        state = _make_state(node_status="foo")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# extract_claims: next / retry / escalate
# ============================================================


class TestExtractClaimsRouting:
    """Tests for extract_claims node routing."""

    def test_completed_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("extract_claims", config)
        state = _make_state(node_status="completed")
        assert route(state) == "next"

    def test_transient_error_below_max_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("extract_claims", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"extract_claims": 0},
        )
        assert route(state) == "retry"

    def test_transient_error_at_max_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("extract_claims", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"extract_claims": 3},
        )
        assert route(state) == "escalate"

    def test_permanent_error_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("extract_claims", config)
        state = _make_state(node_status="error", error_type="permanent")
        assert route(state) == "escalate"


# ============================================================
# match_rules: next / retry / escalate
# ============================================================


class TestMatchRulesRouting:
    """Tests for match_rules node routing."""

    def test_completed_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("match_rules", config)
        state = _make_state(node_status="completed")
        assert route(state) == "next"

    def test_transient_error_below_max_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("match_rules", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"match_rules": 2},
        )
        assert route(state) == "retry"

    def test_transient_error_at_max_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("match_rules", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"match_rules": 3},
        )
        assert route(state) == "escalate"

    def test_permanent_error_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("match_rules", config)
        state = _make_state(node_status="error", error_type="permanent")
        assert route(state) == "escalate"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("match_rules", config)
        state = _make_state(node_status="invalid")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# score_confidence: next / retry / escalate
# ============================================================


class TestScoreConfidenceRouting:
    """Tests for score_confidence node routing."""

    def test_completed_returns_next(self, config: PipelineConfig) -> None:
        route = make_routing_fn("score_confidence", config)
        state = _make_state(node_status="completed")
        assert route(state) == "next"

    def test_transient_error_below_max_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("score_confidence", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"score_confidence": 1},
        )
        assert route(state) == "retry"

    def test_transient_error_at_max_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("score_confidence", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"score_confidence": 3},
        )
        assert route(state) == "escalate"

    def test_permanent_error_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("score_confidence", config)
        state = _make_state(node_status="error", error_type="permanent")
        assert route(state) == "escalate"


# ============================================================
# route_to_queue: escalate bucket logic
# ============================================================


class TestRouteToQueueRouting:
    """Tests for route_to_queue node routing (escalate bucket check)."""

    def test_completed_with_escalate_items_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        """Non-empty escalate bucket → route to human_review."""
        route = make_routing_fn("route_to_queue", config)
        state = _make_state(
            node_status="completed",
            queue_buckets=QueueBuckets(
                auto_approve=["claim-1"],
                escalate=["claim-2"],
                auto_reject=[],
            ),
        )
        assert route(state) == "escalate"

    def test_completed_with_empty_escalate_returns_next(
        self, config: PipelineConfig
    ) -> None:
        """Empty escalate bucket → route directly to finalize."""
        route = make_routing_fn("route_to_queue", config)
        state = _make_state(
            node_status="completed",
            queue_buckets=QueueBuckets(
                auto_approve=["claim-1"],
                escalate=[],
                auto_reject=["claim-3"],
            ),
        )
        assert route(state) == "next"

    def test_completed_all_empty_buckets_returns_next(
        self, config: PipelineConfig
    ) -> None:
        """All buckets empty → still routes to finalize (next)."""
        route = make_routing_fn("route_to_queue", config)
        state = _make_state(
            node_status="completed",
            queue_buckets=QueueBuckets(
                auto_approve=[],
                escalate=[],
                auto_reject=[],
            ),
        )
        assert route(state) == "next"

    def test_transient_error_below_max_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("route_to_queue", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"route_to_queue": 1},
        )
        assert route(state) == "retry"

    def test_transient_error_at_max_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("route_to_queue", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"route_to_queue": 3},
        )
        assert route(state) == "escalate"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("route_to_queue", config)
        state = _make_state(node_status="weird")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# human_review: always → finalize
# ============================================================


class TestHumanReviewRouting:
    """Tests for human_review node routing (always finalize on completed)."""

    def test_completed_returns_finalize(self, config: PipelineConfig) -> None:
        route = make_routing_fn("human_review", config)
        state = _make_state(node_status="completed")
        assert route(state) == "finalize"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("human_review", config)
        state = _make_state(node_status="error", error_type="transient")
        assert route(state) == "escalate"

    def test_unknown_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("human_review", config)
        state = _make_state(node_status="gibberish")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# finalize: end / retry / escalate
# ============================================================


class TestFinalizeRouting:
    """Tests for finalize node routing (end/retry/escalate)."""

    def test_completed_returns_end(self, config: PipelineConfig) -> None:
        route = make_routing_fn("finalize", config)
        state = _make_state(node_status="completed")
        assert route(state) == "end"

    def test_transient_error_below_max_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("finalize", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"finalize": 2},
        )
        assert route(state) == "retry"

    def test_transient_error_at_max_returns_escalate(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("finalize", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={"finalize": 3},
        )
        assert route(state) == "escalate"

    def test_permanent_error_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("finalize", config)
        state = _make_state(node_status="error", error_type="permanent")
        assert route(state) == "escalate"

    def test_unhandled_status_returns_escalate(self, config: PipelineConfig) -> None:
        route = make_routing_fn("finalize", config)
        state = _make_state(node_status="???")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# General: unhandled state fallback for all nodes
# ============================================================


class TestUnhandledStateFallback:
    """Tests that unhandled node_status values always return 'escalate'."""

    @pytest.mark.parametrize(
        "node_name",
        [
            "ingest",
            "extract_text",
            "chunk",
            "embed",
            "extract_claims",
            "match_rules",
            "score_confidence",
            "route_to_queue",
            "human_review",
            "finalize",
        ],
    )
    def test_unrecognized_status_escalates(
        self, config: PipelineConfig, node_name: str
    ) -> None:
        """Every node must escalate on unrecognized node_status."""
        route = make_routing_fn(node_name, config)
        state = _make_state(node_status="unrecognized_state_xyz")  # type: ignore[arg-type]
        assert route(state) == "escalate"


# ============================================================
# Edge case: retries dict missing the node key
# ============================================================


class TestMissingRetryCount:
    """Tests that nodes handle missing retry count gracefully (default 0)."""

    def test_general_node_missing_retry_key_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        """If retries dict doesn't have the node key, default is 0 (< max) → retry."""
        route = make_routing_fn("extract_text", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={},  # no key for extract_text
        )
        assert route(state) == "retry"

    def test_finalize_missing_retry_key_returns_retry(
        self, config: PipelineConfig
    ) -> None:
        route = make_routing_fn("finalize", config)
        state = _make_state(
            node_status="error",
            error_type="transient",
            retries={},  # no key for finalize
        )
        assert route(state) == "retry"
