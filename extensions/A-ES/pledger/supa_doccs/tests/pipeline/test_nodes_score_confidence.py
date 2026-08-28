"""Unit tests for the score_confidence node.

Tests cover:
- Successful scoring with flagging below threshold
- Claims at/above threshold have needs_human_review=false
- Non-compliant verdicts always get needs_human_review=true regardless of confidence
- Empty verdicts → completed (not error)
- Transient error on scoring service failure
- Permanent error on config issue
- That completed_nodes includes "score_confidence" on success
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.nodes.score_confidence import (
    ConfidenceScoringService,
    score_confidence,
)
from src.pipeline.state import (
    ChunkEntry,
    ComplianceVerdict,
    PipelineState,
    create_initial_state,
)


# --- Test helpers ---


def _make_config(**overrides):
    """Create a pipeline config with optional overrides."""
    return load_config(overrides if overrides else None)


def _make_state(
    verdicts: list[ComplianceVerdict] | None = None,
    chunks: list[ChunkEntry] | None = None,
    config=None,
    completed_nodes: list[str] | None = None,
) -> PipelineState:
    """Create a minimal PipelineState for score_confidence tests."""
    cfg = config if config is not None else _make_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=cfg,
    )
    if verdicts is not None:
        state["verdicts"] = verdicts
    if chunks is not None:
        state["chunks"] = chunks
    if completed_nodes is not None:
        state["completed_nodes"] = completed_nodes
    return state


def _make_verdict(
    claim_id: str = "claim-1",
    verdict: str = "compliant",
    confidence: float = 0.8,
    needs_human_review: bool = False,
    rule_id: str | None = "rule-1",
    evidence_refs: list[str] | None = None,
) -> ComplianceVerdict:
    """Create a ComplianceVerdict for testing."""
    return ComplianceVerdict(
        claim_id=claim_id,
        verdict=verdict,  # type: ignore[typeddict-item]
        confidence=confidence,
        needs_human_review=needs_human_review,
        rule_id=rule_id,
        evidence_refs=evidence_refs or [],
    )


def _make_chunk(index: int = 0, text: str = "sample chunk text") -> ChunkEntry:
    """Create a ChunkEntry for testing."""
    return ChunkEntry(
        index=index,
        text=text,
        start_offset=0,
        end_offset=len(text),
    )


# --- Mock scoring service ---


class MockScoringService:
    """Mock scoring service for testing dependency injection."""

    def __init__(
        self,
        should_fail: bool = False,
        refined_confidence: float | None = None,
    ):
        self.should_fail = should_fail
        self.refined_confidence = refined_confidence
        self.called_with_verdicts: list[ComplianceVerdict] | None = None
        self.called_with_chunks: list[ChunkEntry] | None = None

    async def refine_scores(
        self, verdicts: list[ComplianceVerdict], chunks: list[ChunkEntry]
    ) -> list[ComplianceVerdict]:
        self.called_with_verdicts = verdicts
        self.called_with_chunks = chunks

        if self.should_fail:
            raise RuntimeError("LLM API connection timeout")

        if self.refined_confidence is not None:
            refined = []
            for v in verdicts:
                updated = dict(v)
                updated["confidence"] = self.refined_confidence
                refined.append(ComplianceVerdict(**updated))  # type: ignore[typeddict-item]
            return refined

        return verdicts


# ============================================================
# Successful scoring with threshold flagging
# ============================================================


class TestSuccessfulScoring:
    """Tests for successful confidence scoring and flagging."""

    @pytest.mark.anyio
    async def test_claim_below_threshold_flagged(self):
        """Claims with confidence below threshold get needs_human_review=True."""
        config = _make_config(confidence_threshold=0.7)
        verdicts = [_make_verdict(confidence=0.5, needs_human_review=False)]
        state = _make_state(verdicts=verdicts, config=config)

        result = await score_confidence(state)

        assert result["node_status"] == "completed"
        assert result["verdicts"][0]["needs_human_review"] is True

    @pytest.mark.anyio
    async def test_claim_above_threshold_not_flagged(self):
        """Claims with confidence above threshold get needs_human_review=False."""
        config = _make_config(confidence_threshold=0.7)
        verdicts = [_make_verdict(confidence=0.9, needs_human_review=True)]
        state = _make_state(verdicts=verdicts, config=config)

        result = await score_confidence(state)

        assert result["node_status"] == "completed"
        assert result["verdicts"][0]["needs_human_review"] is False

    @pytest.mark.anyio
    async def test_claim_at_threshold_not_flagged(self):
        """Claims with confidence exactly at threshold get needs_human_review=False."""
        config = _make_config(confidence_threshold=0.7)
        verdicts = [_make_verdict(confidence=0.7, needs_human_review=True)]
        state = _make_state(verdicts=verdicts, config=config)

        result = await score_confidence(state)

        assert result["node_status"] == "completed"
        assert result["verdicts"][0]["needs_human_review"] is False

    @pytest.mark.anyio
    async def test_multiple_verdicts_mixed_flagging(self):
        """Multiple verdicts get correctly flagged based on individual confidence."""
        config = _make_config(confidence_threshold=0.7)
        verdicts = [
            _make_verdict(claim_id="c1", confidence=0.5),  # below
            _make_verdict(claim_id="c2", confidence=0.8),  # above
            _make_verdict(claim_id="c3", confidence=0.7),  # at threshold
            _make_verdict(claim_id="c4", confidence=0.3),  # well below
        ]
        state = _make_state(verdicts=verdicts, config=config)

        result = await score_confidence(state)

        assert result["node_status"] == "completed"
        assert result["verdicts"][0]["needs_human_review"] is True  # c1: 0.5
        assert result["verdicts"][1]["needs_human_review"] is False  # c2: 0.8
        assert result["verdicts"][2]["needs_human_review"] is False  # c3: 0.7
        assert result["verdicts"][3]["needs_human_review"] is True  # c4: 0.3


# ============================================================
# Non-compliant verdicts always flagged
# ============================================================


class TestNonCompliantAlwaysFlagged:
    """Non-compliant verdicts always get needs_human_review=True."""

    @pytest.mark.anyio
    async def test_non_compliant_high_confidence_still_flagged(self):
        """Non-compliant verdicts with high confidence still get needs_human_review=True."""
        config = _make_config(confidence_threshold=0.7)
        verdicts = [
            _make_verdict(
                verdict="non_compliant", confidence=0.95, needs_human_review=False
            )
        ]
        state = _make_state(verdicts=verdicts, config=config)

        result = await score_confidence(state)

        assert result["node_status"] == "completed"
        assert result["verdicts"][0]["needs_human_review"] is True

    @pytest.mark.anyio
    async def test_non_compliant_low_confidence_flagged(self):
        """Non-compliant verdicts with low confidence get needs_human_review=True."""
        config = _make_config(confidence_threshold=0.7)
        verdicts = [
            _make_verdict(
                verdict="non_compliant", confidence=0.3, needs_human_review=False
            )
        ]
        state = _make_state(verdicts=verdicts, config=config)

        result = await score_confidence(state)

        assert result["node_status"] == "completed"
        assert result["verdicts"][0]["needs_human_review"] is True

    @pytest.mark.anyio
    async def test_compliant_high_confidence_not_flagged(self):
        """Compliant verdicts with high confidence are not flagged."""
        config = _make_config(confidence_threshold=0.7)
        verdicts = [
            _make_verdict(verdict="compliant", confidence=0.95)
        ]
        state = _make_state(verdicts=verdicts, config=config)

        result = await score_confidence(state)

        assert result["verdicts"][0]["needs_human_review"] is False

    @pytest.mark.anyio
    async def test_indeterminate_below_threshold_flagged(self):
        """Indeterminate verdicts below threshold are flagged."""
        config = _make_config(confidence_threshold=0.7)
        verdicts = [
            _make_verdict(verdict="indeterminate", confidence=0.5)
        ]
        state = _make_state(verdicts=verdicts, config=config)

        result = await score_confidence(state)

        assert result["verdicts"][0]["needs_human_review"] is True


# ============================================================
# Empty verdicts → completed (not error)
# ============================================================


class TestEmptyVerdicts:
    """Empty verdicts list results in completed status."""

    @pytest.mark.anyio
    async def test_empty_verdicts_returns_completed(self):
        """Empty verdicts list completes successfully with empty list."""
        state = _make_state(verdicts=[])

        result = await score_confidence(state)

        assert result["node_status"] == "completed"
        assert result["verdicts"] == []
        assert result["error_type"] is None
        assert result["error_detail"] is None

    @pytest.mark.anyio
    async def test_empty_verdicts_includes_completed_nodes(self):
        """Empty verdicts still appends to completed_nodes."""
        state = _make_state(verdicts=[], completed_nodes=["match_rules"])

        result = await score_confidence(state)

        assert "score_confidence" in result["completed_nodes"]
        assert "match_rules" in result["completed_nodes"]


# ============================================================
# Transient error on scoring service failure
# ============================================================


class TestTransientError:
    """Transient error when scoring service fails."""

    @pytest.mark.anyio
    async def test_scoring_service_failure_returns_transient_error(self):
        """LLM API failure in scoring service results in transient error."""
        verdicts = [_make_verdict(confidence=0.8)]
        state = _make_state(verdicts=verdicts)
        service = MockScoringService(should_fail=True)

        result = await score_confidence(state, scoring_service=service)

        assert result["node_status"] == "error"
        assert result["error_type"] == "transient"
        assert "Scoring service failure" in result["error_detail"]
        assert result["current_node"] == "score_confidence"

    @pytest.mark.anyio
    async def test_transient_error_does_not_append_completed_nodes(self):
        """On transient error, score_confidence is NOT added to completed_nodes."""
        verdicts = [_make_verdict()]
        state = _make_state(verdicts=verdicts, completed_nodes=["match_rules"])
        service = MockScoringService(should_fail=True)

        result = await score_confidence(state, scoring_service=service)

        assert "score_confidence" not in result["completed_nodes"]
        assert "match_rules" in result["completed_nodes"]


# ============================================================
# Permanent error on config issue
# ============================================================


class TestPermanentError:
    """Permanent error on rule config issues."""

    @pytest.mark.anyio
    async def test_missing_config_returns_permanent_error(self):
        """Missing config entirely results in permanent error."""
        state = _make_state(verdicts=[_make_verdict()])
        # Manually remove config to simulate config issue
        state["config"] = None  # type: ignore[typeddict-item]

        result = await score_confidence(state)

        assert result["node_status"] == "error"
        assert result["error_type"] == "permanent"
        assert "config" in result["error_detail"].lower()
        assert result["current_node"] == "score_confidence"

    @pytest.mark.anyio
    async def test_permanent_error_does_not_append_completed_nodes(self):
        """On permanent error, score_confidence is NOT added to completed_nodes."""
        state = _make_state(verdicts=[_make_verdict()], completed_nodes=["match_rules"])
        state["config"] = None  # type: ignore[typeddict-item]

        result = await score_confidence(state)

        assert "score_confidence" not in result["completed_nodes"]
        assert "match_rules" in result["completed_nodes"]


# ============================================================
# completed_nodes includes "score_confidence" on success
# ============================================================


class TestCompletedNodes:
    """Verify completed_nodes is properly updated."""

    @pytest.mark.anyio
    async def test_completed_nodes_includes_score_confidence(self):
        """On success, completed_nodes should include 'score_confidence'."""
        verdicts = [_make_verdict(confidence=0.8)]
        state = _make_state(verdicts=verdicts)

        result = await score_confidence(state)

        assert result["node_status"] == "completed"
        assert "score_confidence" in result["completed_nodes"]

    @pytest.mark.anyio
    async def test_completed_nodes_preserves_prior_entries(self):
        """score_confidence appends to existing completed_nodes entries."""
        verdicts = [_make_verdict(confidence=0.8)]
        state = _make_state(
            verdicts=verdicts,
            completed_nodes=["ingest", "extract_text", "chunk", "embed", "extract_claims", "match_rules"],
        )

        result = await score_confidence(state)

        assert result["completed_nodes"] == [
            "ingest", "extract_text", "chunk", "embed",
            "extract_claims", "match_rules", "score_confidence",
        ]


# ============================================================
# Scoring service dependency injection
# ============================================================


class TestScoringServiceInjection:
    """Tests for the optional scoring service dependency injection."""

    @pytest.mark.anyio
    async def test_no_service_keeps_existing_scores(self):
        """Without scoring service, existing confidence scores are preserved."""
        verdicts = [_make_verdict(confidence=0.85)]
        state = _make_state(verdicts=verdicts)

        result = await score_confidence(state)

        assert result["verdicts"][0]["confidence"] == 0.85

    @pytest.mark.anyio
    async def test_service_refines_scores(self):
        """Scoring service can refine confidence scores."""
        verdicts = [_make_verdict(confidence=0.8)]
        chunks = [_make_chunk()]
        state = _make_state(verdicts=verdicts, chunks=chunks)
        service = MockScoringService(refined_confidence=0.5)

        result = await score_confidence(state, scoring_service=service)

        # Service refined to 0.5, which is below default threshold 0.7
        assert result["verdicts"][0]["confidence"] == 0.5
        assert result["verdicts"][0]["needs_human_review"] is True

    @pytest.mark.anyio
    async def test_service_receives_verdicts_and_chunks(self):
        """Scoring service receives the verdicts and chunks from state."""
        verdicts = [_make_verdict(claim_id="test-claim")]
        chunks = [_make_chunk(index=0, text="test text")]
        state = _make_state(verdicts=verdicts, chunks=chunks)
        service = MockScoringService()

        await score_confidence(state, scoring_service=service)

        assert service.called_with_verdicts is not None
        assert len(service.called_with_verdicts) == 1
        assert service.called_with_verdicts[0]["claim_id"] == "test-claim"
        assert service.called_with_chunks is not None
        assert len(service.called_with_chunks) == 1
