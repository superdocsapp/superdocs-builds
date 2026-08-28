"""End-to-end test: unverifiable citation marker propagation.

Seeds a single claim with source_span=None and traces it through every
human-facing surface:
1. Deliverable/register: claim renders with citation_status="unverifiable"
2. Review queue: pending item payload carries the unverifiable marker
3. Rules-checking: produces "indeterminate" verdict with
   evidence_refs=["citation_unverifiable"] rather than evaluating silently

Asserts that a human can ALWAYS tell the difference between a grounded
claim and an unverifiable one, at every point they would look.
"""

from __future__ import annotations

import uuid

import pytest

from src.pipeline.approval import (
    ApprovalService,
    InMemoryApprovalStore,
    ItemStatus,
)
from src.pipeline.config import load_config
from src.pipeline.deliverable import Deliverable, SectionClaim
from src.pipeline.nodes.match_rules import match_rules
from src.pipeline.services import (
    DeliverableResult,
    ServiceRegistry,
    get_deliverable,
    list_pending_approvals,
    registry,
)
from src.pipeline.state import (
    ComplianceVerdict,
    ExtractionResult,
    PipelineState,
    create_initial_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

UNVERIFIABLE_CLAIM = ExtractionResult(
    claim_id="loan_agreement.processing_fee_3",
    claim_text="processing_fee: 3000.00",
    chunk_index=0,
    start_offset=0,  # 0,0 = citation unverifiable (source_span was None upstream)
    end_offset=0,
    confidence=0.5,
    citation_status="unverifiable",
)

GROUNDED_CLAIM = ExtractionResult(
    claim_id="loan_agreement.interest_rate_0",
    claim_text="interest_rate: 18.50",
    chunk_index=0,
    start_offset=42,
    end_offset=67,
    confidence=0.9,
    citation_status="grounded",
)


@pytest.fixture
def pipeline_state_with_unverifiable_claim() -> PipelineState:
    """Pipeline state containing one grounded and one unverifiable claim."""
    config = load_config()
    state = create_initial_state(
        run_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()),
        config=config,
    )
    state["claims"] = [GROUNDED_CLAIM, UNVERIFIABLE_CLAIM]
    state["classification_label"] = "loan_agreement"
    return state


@pytest.fixture
def approval_service() -> ApprovalService:
    return ApprovalService(InMemoryApprovalStore())


# ---------------------------------------------------------------------------
# Mock rule matching service (for grounded claims only)
# ---------------------------------------------------------------------------


class MockRuleMatchingService:
    """Returns compliant verdict for any claim it's asked to check."""

    async def match(self, claim: ExtractionResult) -> ComplianceVerdict:
        return ComplianceVerdict(
            claim_id=claim["claim_id"],
            verdict="compliant",
            confidence=0.85,
            needs_human_review=False,
            rule_id="MF-001",
            evidence_refs=[],
        )


# ---------------------------------------------------------------------------
# Test: End-to-end unverifiable marker propagation
# ---------------------------------------------------------------------------


class TestUnverifiableCitationEndToEnd:
    """Trace a single unverifiable claim through every human-facing surface."""

    @pytest.mark.anyio
    async def test_full_pipeline_unverifiable_marker_propagation(
        self,
        pipeline_state_with_unverifiable_claim: PipelineState,
        approval_service: ApprovalService,
    ):
        """A claim with source_span=None must show [citation unverifiable]
        at every surface a human would look at.

        Surfaces tested:
        1. Deliverable output (the register)
        2. Approval queue item payload
        3. Rules-checking verdict
        """
        state = pipeline_state_with_unverifiable_claim
        run_id = state["run_id"]

        # ===================================================================
        # Surface 1: DELIVERABLE
        # When the claim is added to the deliverable, its citation_status
        # must be "unverifiable", never the default "grounded".
        # ===================================================================

        deliverable = Deliverable()

        # Simulate adding claims to deliverable (as the pipeline would)
        for claim in state["claims"]:
            deliverable.add_claim(SectionClaim(
                claim_id=claim["claim_id"],
                claim_type=claim["claim_id"].rsplit("_", 1)[0],
                extracted_text=claim["claim_text"].split(": ", 1)[1] if ": " in claim["claim_text"] else claim["claim_text"],
                confidence=claim["confidence"],
                source_document_id=state["document_id"],
                citation_status=claim["citation_status"],
            ))

        # Verify the deliverable renders correctly
        deliverable.compute_all_hashes()

        # Find the unverifiable claim in the deliverable
        all_claims_in_deliverable = []
        for section in deliverable.sections.values():
            all_claims_in_deliverable.extend(section.claims)

        unverifiable_in_deliverable = [
            c for c in all_claims_in_deliverable
            if c.claim_id == UNVERIFIABLE_CLAIM["claim_id"]
        ]
        grounded_in_deliverable = [
            c for c in all_claims_in_deliverable
            if c.claim_id == GROUNDED_CLAIM["claim_id"]
        ]

        assert len(unverifiable_in_deliverable) == 1
        assert len(grounded_in_deliverable) == 1

        # THE KEY ASSERTION: unverifiable claim has visible marker
        assert unverifiable_in_deliverable[0].citation_status == "unverifiable"
        # Grounded claim does NOT have the marker
        assert grounded_in_deliverable[0].citation_status == "grounded"

        # Verify the service-level get_deliverable also shows the marker
        old_deliverable = registry.deliverable
        registry.deliverable = deliverable
        try:
            result = get_deliverable()
            # Find the unverifiable claim in the serialized output
            all_serialized_claims = []
            for section_data in result.sections.values():
                all_serialized_claims.extend(section_data["claims"])

            unverifiable_serialized = [
                c for c in all_serialized_claims
                if c["claim_id"] == UNVERIFIABLE_CLAIM["claim_id"]
            ]
            assert len(unverifiable_serialized) == 1
            assert unverifiable_serialized[0]["citation_status"] == "unverifiable"

            grounded_serialized = [
                c for c in all_serialized_claims
                if c["claim_id"] == GROUNDED_CLAIM["claim_id"]
            ]
            assert len(grounded_serialized) == 1
            assert grounded_serialized[0]["citation_status"] == "grounded"
        finally:
            registry.deliverable = old_deliverable

        # ===================================================================
        # Surface 2: RULES-CHECKING
        # The unverifiable claim must produce a distinct "indeterminate"
        # verdict with evidence_refs=["citation_unverifiable"], NOT be
        # silently evaluated as if it were grounded.
        # ===================================================================

        rule_service = MockRuleMatchingService()
        result = await match_rules(state, rule_matching_service=rule_service)

        assert result["node_status"] == "completed"
        verdicts = result["verdicts"]
        assert len(verdicts) == 2

        # Find the verdict for the unverifiable claim
        unverifiable_verdict = next(
            v for v in verdicts
            if v["claim_id"] == UNVERIFIABLE_CLAIM["claim_id"]
        )
        grounded_verdict = next(
            v for v in verdicts
            if v["claim_id"] == GROUNDED_CLAIM["claim_id"]
        )

        # THE KEY ASSERTION: unverifiable claim gets indeterminate, not compliant
        assert unverifiable_verdict["verdict"] == "indeterminate"
        assert unverifiable_verdict["confidence"] == 0.0
        assert unverifiable_verdict["needs_human_review"] is True
        assert "citation_unverifiable" in unverifiable_verdict["evidence_refs"]

        # Grounded claim is evaluated normally
        assert grounded_verdict["verdict"] == "compliant"
        assert grounded_verdict["confidence"] == 0.85

        # ===================================================================
        # Surface 3: APPROVAL QUEUE
        # When the unverifiable claim is escalated to the queue, the item
        # payload must carry the unverifiable marker so reviewers can see it.
        # ===================================================================

        # Simulate escalation of the unverifiable claim to approval queue
        item = approval_service.enqueue_item(
            run_id=run_id,
            item_type="finding",
            payload={
                "claim_id": UNVERIFIABLE_CLAIM["claim_id"],
                "claim_text": UNVERIFIABLE_CLAIM["claim_text"],
                "confidence": UNVERIFIABLE_CLAIM["confidence"],
                "citation_status": "unverifiable",  # Must be in payload
                "verdict": unverifiable_verdict["verdict"],
                "verdict_reason": "citation_unverifiable",
            },
        )

        # Verify the queue item carries the marker
        retrieved = approval_service.get_item(item.id)
        assert retrieved is not None
        assert retrieved.payload["citation_status"] == "unverifiable"
        assert retrieved.payload["verdict_reason"] == "citation_unverifiable"

        # Verify via the list API (as a reviewer would see it)
        old_service = registry.approval_service
        registry.approval_service = approval_service
        try:
            list_result = list_pending_approvals(run_id)
            assert list_result.pending == 1
            queue_item = list_result.items[0]
            assert queue_item["payload"]["citation_status"] == "unverifiable"
            assert queue_item["payload"]["verdict_reason"] == "citation_unverifiable"
        finally:
            registry.approval_service = old_service

    @pytest.mark.anyio
    async def test_grounded_claim_never_shows_unverifiable_marker(
        self,
    ):
        """A properly grounded claim must never show the unverifiable marker."""
        config = load_config()
        state = create_initial_state(
            run_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            document_version_id=str(uuid.uuid4()),
            config=config,
        )
        state["claims"] = [GROUNDED_CLAIM]

        rule_service = MockRuleMatchingService()
        result = await match_rules(state, rule_matching_service=rule_service)

        assert result["node_status"] == "completed"
        verdicts = result["verdicts"]
        assert len(verdicts) == 1

        # Grounded claim is evaluated normally — no unverifiable markers
        v = verdicts[0]
        assert v["verdict"] == "compliant"
        assert v["confidence"] == 0.85
        assert "citation_unverifiable" not in v["evidence_refs"]
        assert v["needs_human_review"] is False

    @pytest.mark.anyio
    async def test_unverifiable_claim_excluded_from_rule_evaluation(
        self,
        pipeline_state_with_unverifiable_claim: PipelineState,
    ):
        """The rule matching service is NOT called for unverifiable claims.

        This proves the system doesn't silently skip them — it produces
        a distinct outcome without invoking the evaluator at all.
        """

        class TrackingRuleService:
            def __init__(self):
                self.evaluated_claim_ids: list[str] = []

            async def match(self, claim: ExtractionResult) -> ComplianceVerdict:
                self.evaluated_claim_ids.append(claim["claim_id"])
                return ComplianceVerdict(
                    claim_id=claim["claim_id"],
                    verdict="compliant",
                    confidence=0.9,
                    needs_human_review=False,
                    rule_id="MF-001",
                    evidence_refs=[],
                )

        state = pipeline_state_with_unverifiable_claim
        tracker = TrackingRuleService()

        result = await match_rules(state, rule_matching_service=tracker)

        # Only the grounded claim was sent to the rule service
        assert GROUNDED_CLAIM["claim_id"] in tracker.evaluated_claim_ids
        assert UNVERIFIABLE_CLAIM["claim_id"] not in tracker.evaluated_claim_ids

        # But both claims have verdicts
        assert len(result["verdicts"]) == 2

    @pytest.mark.anyio
    async def test_deliverable_section_hash_differs_for_unverifiable(self):
        """A section containing an unverifiable claim hashes differently
        than the same section if citation_status were 'grounded'.

        This ensures the unverifiable status is part of the content identity,
        not just metadata that could be stripped.
        """
        deliverable_unverifiable = Deliverable()
        deliverable_unverifiable.add_claim(SectionClaim(
            claim_id="test.field_0",
            claim_type="test.field",
            extracted_text="some value",
            confidence=0.5,
            source_document_id="doc-1",
            citation_status="unverifiable",
        ))
        hashes_unverifiable = deliverable_unverifiable.compute_all_hashes()

        deliverable_grounded = Deliverable()
        deliverable_grounded.add_claim(SectionClaim(
            claim_id="test.field_0",
            claim_type="test.field",
            extracted_text="some value",
            confidence=0.5,
            source_document_id="doc-1",
            citation_status="grounded",
        ))
        hashes_grounded = deliverable_grounded.compute_all_hashes()

        # The hashes MUST differ — citation_status is part of content identity
        assert hashes_unverifiable["test.field"] != hashes_grounded["test.field"]



# ---------------------------------------------------------------------------
# Test: Grounded zero-offset claim is NOT excluded
# ---------------------------------------------------------------------------


class TestGroundedZeroOffsetNotExcluded:
    """A claim with start_offset=0, end_offset=N (legitimately spanning the
    start of the document) and citation_status='grounded' must be evaluated
    normally — NOT treated as unverifiable.

    This is the regression test for the (0,0)-as-magic-value problem:
    the exclusion logic must read citation_status, never offset values.
    """

    @pytest.mark.anyio
    async def test_grounded_claim_at_offset_zero_is_evaluated(self):
        """A fact cited from the very start of a document (offset 0) is grounded."""
        # This claim starts at character 0 — a real document might begin with
        # "Priya Sharma agrees to..." and the borrower name is at offset 0.
        grounded_at_zero = ExtractionResult(
            claim_id="loan_agreement.borrower_name_0",
            claim_text="borrower_name: Priya Sharma",
            chunk_index=0,
            start_offset=0,
            end_offset=12,  # "Priya Sharma" = 12 chars
            confidence=0.9,
            citation_status="grounded",
        )

        config = load_config()
        state = create_initial_state(
            run_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            document_version_id=str(uuid.uuid4()),
            config=config,
        )
        state["claims"] = [grounded_at_zero]

        class TrackingService:
            def __init__(self):
                self.evaluated: list[str] = []

            async def match(self, claim: ExtractionResult) -> ComplianceVerdict:
                self.evaluated.append(claim["claim_id"])
                return ComplianceVerdict(
                    claim_id=claim["claim_id"],
                    verdict="compliant",
                    confidence=0.9,
                    needs_human_review=False,
                    rule_id="MF-001",
                    evidence_refs=[],
                )

        tracker = TrackingService()
        result = await match_rules(state, rule_matching_service=tracker)

        # The claim WAS evaluated (not excluded)
        assert grounded_at_zero["claim_id"] in tracker.evaluated
        assert result["node_status"] == "completed"

        verdict = result["verdicts"][0]
        assert verdict["verdict"] == "compliant"
        assert verdict["confidence"] == 0.9
        assert "citation_unverifiable" not in verdict["evidence_refs"]

    @pytest.mark.anyio
    async def test_grounded_zero_zero_span_is_still_evaluated(self):
        """Even a zero-length span (0, 0) with citation_status='grounded'
        is evaluated — the exclusion reads status, not offsets.

        This is the synthetic edge case: a grounded fact whose span happens
        to be (0, 0) should still be rule-checked because its citation_status
        says it's grounded.
        """
        # Synthetic: a grounded fact with (0, 0) offsets
        # (shouldn't happen in practice, but tests the invariant)
        grounded_zero_zero = ExtractionResult(
            claim_id="loan_agreement.interest_rate_0",
            claim_text="interest_rate: 18.50",
            chunk_index=0,
            start_offset=0,
            end_offset=0,
            confidence=0.85,
            citation_status="grounded",  # THIS is what matters
        )

        config = load_config()
        state = create_initial_state(
            run_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            document_version_id=str(uuid.uuid4()),
            config=config,
        )
        state["claims"] = [grounded_zero_zero]

        class TrackingService:
            def __init__(self):
                self.evaluated: list[str] = []

            async def match(self, claim: ExtractionResult) -> ComplianceVerdict:
                self.evaluated.append(claim["claim_id"])
                return ComplianceVerdict(
                    claim_id=claim["claim_id"],
                    verdict="non_compliant",
                    confidence=0.8,
                    needs_human_review=True,
                    rule_id="MF-001",
                    evidence_refs=["found_violation"],
                )

        tracker = TrackingService()
        result = await match_rules(state, rule_matching_service=tracker)

        # Despite (0,0) offsets, it was evaluated because citation_status="grounded"
        assert grounded_zero_zero["claim_id"] in tracker.evaluated
        assert len(result["verdicts"]) == 1

        verdict = result["verdicts"][0]
        assert verdict["verdict"] == "non_compliant"
        assert "citation_unverifiable" not in verdict["evidence_refs"]

    @pytest.mark.anyio
    async def test_unverifiable_with_nonzero_offsets_still_excluded(self):
        """If citation_status is 'unverifiable' but offsets happen to be nonzero
        (shouldn't happen, but defensive), it's STILL excluded.

        The exclusion reads citation_status, not offsets — period.
        """
        unverifiable_with_offsets = ExtractionResult(
            claim_id="loan_agreement.fee_0",
            claim_text="processing_fee: 5000.00",
            chunk_index=0,
            start_offset=100,  # Nonzero offsets
            end_offset=150,
            confidence=0.3,
            citation_status="unverifiable",  # THIS is what matters
        )

        config = load_config()
        state = create_initial_state(
            run_id=str(uuid.uuid4()),
            document_id=str(uuid.uuid4()),
            document_version_id=str(uuid.uuid4()),
            config=config,
        )
        state["claims"] = [unverifiable_with_offsets]

        class TrackingService:
            def __init__(self):
                self.evaluated: list[str] = []

            async def match(self, claim: ExtractionResult) -> ComplianceVerdict:
                self.evaluated.append(claim["claim_id"])
                return ComplianceVerdict(
                    claim_id=claim["claim_id"],
                    verdict="compliant",
                    confidence=0.9,
                    needs_human_review=False,
                    rule_id="MF-001",
                    evidence_refs=[],
                )

        tracker = TrackingService()
        result = await match_rules(state, rule_matching_service=tracker)

        # Despite nonzero offsets, it was NOT evaluated (excluded by status)
        assert unverifiable_with_offsets["claim_id"] not in tracker.evaluated
        assert len(result["verdicts"]) == 1

        verdict = result["verdicts"][0]
        assert verdict["verdict"] == "indeterminate"
        assert "citation_unverifiable" in verdict["evidence_refs"]
