"""Unit tests for the route_to_queue node.

Tests cover:
- All claims auto_approved when compliant with high confidence
- Non-compliant claims escalated
- Low confidence claims escalated
- needs_human_review claims escalated
- Duplicate claims auto_rejected
- Priority: claim matching both escalate and auto_reject goes to escalate
- Each claim appears in exactly one bucket
- completed_nodes includes "route_to_queue" on success
- Empty verdicts/claims → empty buckets, still completed
"""

import pytest

from src.pipeline.config import load_config
from src.pipeline.nodes.route_to_queue import route_to_queue
from src.pipeline.state import (
    ComplianceVerdict,
    ExtractionResult,
    PipelineState,
    QueueBuckets,
    create_initial_state,
)


# --- Fixtures ---


@pytest.fixture
def base_state() -> PipelineState:
    """Create a pipeline state ready for route_to_queue."""
    config = load_config()
    state = create_initial_state(
        run_id="test-run-id",
        document_id="test-doc-id",
        document_version_id="test-version-id",
        config=config,
    )
    return state


def _make_claim(
    claim_id: str,
    claim_text: str = "APR is 24%",
    chunk_index: int = 0,
    start_offset: int = 0,
    end_offset: int = 10,
    confidence: float = 0.9,
) -> ExtractionResult:
    """Helper to create an ExtractionResult."""
    return ExtractionResult(
        claim_id=claim_id,
        claim_text=claim_text,
        chunk_index=chunk_index,
        start_offset=start_offset,
        end_offset=end_offset,
        confidence=confidence,
    )


def _make_verdict(
    claim_id: str,
    verdict: str = "compliant",
    confidence: float = 0.9,
    needs_human_review: bool = False,
    rule_id: str | None = None,
    evidence_refs: list[str] | None = None,
) -> ComplianceVerdict:
    """Helper to create a ComplianceVerdict."""
    return ComplianceVerdict(
        claim_id=claim_id,
        verdict=verdict,
        confidence=confidence,
        needs_human_review=needs_human_review,
        rule_id=rule_id,
        evidence_refs=evidence_refs or [],
    )


# --- Tests ---


@pytest.mark.anyio
async def test_all_claims_auto_approved_when_compliant_high_confidence(
    base_state: PipelineState,
):
    """All claims land in auto_approve when compliant with confidence >= threshold."""
    base_state["claims"] = [
        _make_claim("c1", claim_text="Claim one", start_offset=0, end_offset=9),
        _make_claim("c2", claim_text="Claim two", start_offset=10, end_offset=19),
        _make_claim("c3", claim_text="Claim three", start_offset=20, end_offset=31),
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
        _make_verdict("c2", verdict="compliant", confidence=0.85),
        _make_verdict("c3", verdict="compliant", confidence=1.0),
    ]

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    assert set(result["queue_buckets"]["auto_approve"]) == {"c1", "c2", "c3"}
    assert result["queue_buckets"]["escalate"] == []
    assert result["queue_buckets"]["auto_reject"] == []


@pytest.mark.anyio
async def test_non_compliant_claims_escalated(base_state: PipelineState):
    """Non-compliant verdict claims should be escalated."""
    base_state["claims"] = [
        _make_claim("c1", claim_text="Claim one", start_offset=0, end_offset=9),
        _make_claim("c2", claim_text="Claim two", start_offset=10, end_offset=19),
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
        _make_verdict("c2", verdict="non_compliant", confidence=0.95),
    ]

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    assert "c1" in result["queue_buckets"]["auto_approve"]
    assert "c2" in result["queue_buckets"]["escalate"]
    assert "c2" not in result["queue_buckets"]["auto_approve"]


@pytest.mark.anyio
async def test_low_confidence_claims_escalated(base_state: PipelineState):
    """Claims with confidence below threshold should be escalated."""
    base_state["claims"] = [
        _make_claim("c1", claim_text="Claim one", start_offset=0, end_offset=9),
        _make_claim("c2", claim_text="Claim two", start_offset=10, end_offset=19),
    ]
    # Default threshold is 0.7
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
        _make_verdict("c2", verdict="compliant", confidence=0.5),
    ]

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    assert "c1" in result["queue_buckets"]["auto_approve"]
    assert "c2" in result["queue_buckets"]["escalate"]


@pytest.mark.anyio
async def test_needs_human_review_claims_escalated(base_state: PipelineState):
    """Claims flagged with needs_human_review should be escalated."""
    base_state["claims"] = [
        _make_claim("c1", claim_text="Claim one", start_offset=0, end_offset=9),
        _make_claim("c2", claim_text="Claim two", start_offset=10, end_offset=19),
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
        _make_verdict(
            "c2", verdict="compliant", confidence=0.9, needs_human_review=True
        ),
    ]

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    assert "c1" in result["queue_buckets"]["auto_approve"]
    assert "c2" in result["queue_buckets"]["escalate"]


@pytest.mark.anyio
async def test_duplicate_claims_auto_rejected(base_state: PipelineState):
    """Duplicate claims (same text, chunk_index, start_offset, end_offset) are auto_rejected."""
    # Two claims with identical fingerprint
    base_state["claims"] = [
        _make_claim(
            "c1",
            claim_text="APR is 24%",
            chunk_index=0,
            start_offset=0,
            end_offset=10,
        ),
        _make_claim(
            "c2",
            claim_text="APR is 24%",
            chunk_index=0,
            start_offset=0,
            end_offset=10,
        ),
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
        _make_verdict("c2", verdict="compliant", confidence=0.9),
    ]

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    # First occurrence auto_approved, second is the duplicate
    assert "c1" in result["queue_buckets"]["auto_approve"]
    assert "c2" in result["queue_buckets"]["auto_reject"]


@pytest.mark.anyio
async def test_priority_escalate_over_auto_reject(base_state: PipelineState):
    """A claim matching both escalate and auto_reject goes to escalate (higher priority)."""
    # c2 is a duplicate of c1 AND is non-compliant → should escalate, not auto_reject
    base_state["claims"] = [
        _make_claim(
            "c1",
            claim_text="APR is 24%",
            chunk_index=0,
            start_offset=0,
            end_offset=10,
        ),
        _make_claim(
            "c2",
            claim_text="APR is 24%",
            chunk_index=0,
            start_offset=0,
            end_offset=10,
        ),
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
        _make_verdict("c2", verdict="non_compliant", confidence=0.95),
    ]

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    # c2 is both duplicate AND non-compliant — escalate wins
    assert "c2" in result["queue_buckets"]["escalate"]
    assert "c2" not in result["queue_buckets"]["auto_reject"]
    assert "c2" not in result["queue_buckets"]["auto_approve"]


@pytest.mark.anyio
async def test_each_claim_in_exactly_one_bucket(base_state: PipelineState):
    """Every claim_id appears in exactly one bucket, no duplicates across buckets."""
    base_state["claims"] = [
        _make_claim("c1", claim_text="Claim A", chunk_index=0, start_offset=0, end_offset=7),
        _make_claim("c2", claim_text="Claim B", chunk_index=0, start_offset=8, end_offset=15),
        _make_claim("c3", claim_text="Claim C", chunk_index=1, start_offset=0, end_offset=7),
        _make_claim(
            "c4", claim_text="Claim A", chunk_index=0, start_offset=0, end_offset=7
        ),  # duplicate of c1
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
        _make_verdict("c2", verdict="non_compliant", confidence=0.8),
        _make_verdict("c3", verdict="compliant", confidence=0.5),
        _make_verdict("c4", verdict="compliant", confidence=0.9),
    ]

    result = await route_to_queue(base_state)

    buckets = result["queue_buckets"]
    all_ids = buckets["auto_approve"] + buckets["escalate"] + buckets["auto_reject"]

    # All claim IDs present
    assert set(all_ids) == {"c1", "c2", "c3", "c4"}
    # No duplicates across buckets
    assert len(all_ids) == len(set(all_ids))


@pytest.mark.anyio
async def test_completed_nodes_includes_route_to_queue(base_state: PipelineState):
    """completed_nodes should include 'route_to_queue' on success."""
    base_state["claims"] = [
        _make_claim("c1", claim_text="Claim one", start_offset=0, end_offset=9),
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
    ]
    base_state["completed_nodes"] = ["ingest", "extract_text", "chunk"]

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    assert "route_to_queue" in result["completed_nodes"]
    assert result["completed_nodes"] == [
        "ingest",
        "extract_text",
        "chunk",
        "route_to_queue",
    ]


@pytest.mark.anyio
async def test_empty_verdicts_and_claims_still_completed(base_state: PipelineState):
    """Empty verdicts and claims should produce empty buckets with completed status."""
    base_state["claims"] = []
    base_state["verdicts"] = []

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    assert result["queue_buckets"]["auto_approve"] == []
    assert result["queue_buckets"]["escalate"] == []
    assert result["queue_buckets"]["auto_reject"] == []
    assert "route_to_queue" in result["completed_nodes"]


@pytest.mark.anyio
async def test_permanent_error_escalates_all_claims(base_state: PipelineState):
    """When state has error_type='permanent', all claims should be escalated."""
    base_state["claims"] = [
        _make_claim("c1", claim_text="Claim one", start_offset=0, end_offset=9),
        _make_claim("c2", claim_text="Claim two", start_offset=10, end_offset=19),
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
        _make_verdict("c2", verdict="compliant", confidence=0.9),
    ]
    # Simulate arriving from permanent error escalation
    base_state["error_type"] = "permanent"

    result = await route_to_queue(base_state)

    assert result["node_status"] == "completed"
    assert set(result["queue_buckets"]["escalate"]) == {"c1", "c2"}
    assert result["queue_buckets"]["auto_approve"] == []
    assert result["queue_buckets"]["auto_reject"] == []


@pytest.mark.anyio
async def test_error_type_cleared_on_success(base_state: PipelineState):
    """On successful completion, error_type and error_detail should be cleared."""
    base_state["claims"] = [
        _make_claim("c1", claim_text="Claim one", start_offset=0, end_offset=9),
    ]
    base_state["verdicts"] = [
        _make_verdict("c1", verdict="compliant", confidence=0.9),
    ]

    result = await route_to_queue(base_state)

    assert result["error_type"] is None
    assert result["error_detail"] is None
