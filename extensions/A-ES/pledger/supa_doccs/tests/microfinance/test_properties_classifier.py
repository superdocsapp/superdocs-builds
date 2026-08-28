"""Property-based tests for document classification (Properties 1, 2).

Feature: microfinance-ingestion-pipeline
Tests the classify_document node's output validity and MIME type rejection.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from unittest.mock import AsyncMock, MagicMock

from src.pipeline.nodes.classify_document import (
    SUPPORTED_MIME_TYPES,
    ClassificationResult,
    classify_document,
)
from src.pipeline.state import PipelineState, create_initial_state, PipelineConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_LABELS = {"loan_agreement", "modification_agreement", "repayment_statement"}
ALL_LABELS_WITH_UNCLASSIFIED = VALID_LABELS | {"unclassified"}

_DEFAULT_CONFIG = PipelineConfig(
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


def _make_state(text: str, mime_type: str = "text/plain") -> PipelineState:
    """Create a minimal pipeline state for testing classification."""
    state = create_initial_state(
        run_id="00000000-0000-0000-0000-000000000001",
        document_id="00000000-0000-0000-0000-000000000002",
        document_version_id="00000000-0000-0000-0000-000000000003",
        config=_DEFAULT_CONFIG,
    )
    state["extracted_text"] = text
    state["mime_type"] = mime_type
    return state


def _make_classifier_mock(
    label: str, confidence: float, scores: dict[str, float]
) -> MagicMock:
    """Create a mock classifier that returns the specified result."""
    mock = MagicMock()
    mock.classify = AsyncMock(
        return_value=ClassificationResult(
            label=label,  # type: ignore[arg-type]
            confidence=confidence,
            scores=scores,
        )
    )
    return mock


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for per-label scores: 3 scores in [0.0, 1.0]
@st.composite
def classification_scores_above_threshold(draw: st.DrawFn) -> dict[str, float]:
    """Generate scores where at least one score is above 0.6."""
    scores = {}
    # Ensure at least one label has score > 0.6
    high_label = draw(st.sampled_from(sorted(VALID_LABELS)))
    high_score = draw(st.floats(min_value=0.601, max_value=1.0, allow_nan=False, allow_infinity=False))
    for label in sorted(VALID_LABELS):
        if label == high_label:
            scores[label] = high_score
        else:
            scores[label] = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    return scores


@st.composite
def classification_scores_below_threshold(draw: st.DrawFn) -> dict[str, float]:
    """Generate scores where ALL scores are <= 0.6."""
    scores = {}
    for label in sorted(VALID_LABELS):
        scores[label] = draw(st.floats(min_value=0.0, max_value=0.6, allow_nan=False, allow_infinity=False))
    return scores


# ---------------------------------------------------------------------------
# Property 1: Classification Output Validity
# ---------------------------------------------------------------------------


class TestProperty1ClassificationOutputValidity:
    """Property 1: For any non-empty text with a supported MIME type, classifier
    produces exactly one label from valid set, confidence in [0.0, 1.0],
    label is "unclassified" iff all scores <= 0.6.

    **Validates: Requirements 1.1, 1.2**
    """

    @pytest.mark.anyio
    @given(
        text=st.text(min_size=1, max_size=200).filter(lambda t: t.strip()),
        scores=classification_scores_above_threshold(),
    )
    @settings(max_examples=100)
    async def test_valid_classification_above_threshold(
        self, text: str, scores: dict[str, float]
    ):
        """When max score > 0.6, label is one of the valid document types."""
        # Find the label with the highest score
        best_label = max(scores, key=lambda k: scores[k])
        confidence = scores[best_label]

        classifier = _make_classifier_mock(
            label=best_label,
            confidence=confidence,
            scores=scores,
        )

        state = _make_state(text)
        result = await classify_document(state, classifier=classifier)

        # Verify exactly one label from valid set (not "unclassified")
        assert result["classification_label"] in VALID_LABELS
        # Verify confidence in [0.0, 1.0]
        assert 0.0 <= result["classification_confidence"] <= 1.0
        # Verify label is NOT "unclassified" when a score > 0.6
        assert result["classification_label"] != "unclassified"
        # Verify node completed
        assert result["node_status"] == "completed"

    @pytest.mark.anyio
    @given(
        text=st.text(min_size=1, max_size=200).filter(lambda t: t.strip()),
        scores=classification_scores_below_threshold(),
    )
    @settings(max_examples=100)
    async def test_unclassified_when_all_scores_below_threshold(
        self, text: str, scores: dict[str, float]
    ):
        """When all scores <= 0.6, label is "unclassified"."""
        # The mock classifier returns a result, but classify_document
        # overrides the label to "unclassified" based on scores
        best_label = max(scores, key=lambda k: scores[k])
        confidence = scores[best_label]

        classifier = _make_classifier_mock(
            label=best_label,
            confidence=confidence,
            scores=scores,
        )

        state = _make_state(text)
        result = await classify_document(state, classifier=classifier)

        # When all scores <= 0.6, label MUST be "unclassified"
        assert result["classification_label"] == "unclassified"
        # Confidence is still stored
        assert result["classification_confidence"] is not None
        assert 0.0 <= result["classification_confidence"] <= 1.0
        # Node still completes (routing handles escalation)
        assert result["node_status"] == "completed"


# ---------------------------------------------------------------------------
# Property 2: Unsupported MIME Rejection
# ---------------------------------------------------------------------------


class TestProperty2UnsupportedMIMEReection:
    """Property 2: For any MIME type not in supported set, node returns
    UNSUPPORTED_FORMAT error.

    **Validates: Requirements 1.4**
    """

    @pytest.mark.anyio
    @given(
        mime_type=st.text(min_size=1, max_size=100).filter(
            lambda m: m not in SUPPORTED_MIME_TYPES
        ),
    )
    @settings(max_examples=100)
    async def test_unsupported_mime_returns_error(self, mime_type: str):
        """Any MIME type not in supported set produces UNSUPPORTED_FORMAT error."""
        state = _make_state("Some document text", mime_type=mime_type)

        # Classifier should not even be called for unsupported MIME
        classifier = _make_classifier_mock(
            label="loan_agreement",
            confidence=0.9,
            scores={"loan_agreement": 0.9, "modification_agreement": 0.1, "repayment_statement": 0.0},
        )

        result = await classify_document(state, classifier=classifier)

        # Verify error state
        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert "UNSUPPORTED_FORMAT" in result["error_detail"]
        # Classifier should not have been called
        classifier.classify.assert_not_awaited()
