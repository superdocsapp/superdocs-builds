"""Tests for the incremental update API path.

These tests prove the two key invariants of the incremental update path
as exposed via the API endpoint (POST /piles/{pile_id}/incremental):

1. Hash-identity test: adding an unrelated document to a pile that already
   has a completed deliverable leaves all unaffected sections with identical
   SHA-256 hashes — byte-for-byte unchanged.

2. Contradiction test: adding a document that conflicts with existing claims
   creates a pending approval queue item and does NOT silently overwrite the
   deliverable.

These tests exercise the API module's internal functions directly (unit-level),
avoiding the need for a running database or LLM. The integration point is
_build_deliverable_from_run_state + IncrementalUpdateEngine + ApprovalService.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.pipeline.approval import (
    ApprovalService,
    InMemoryApprovalStore,
    ItemStatus,
)
from src.pipeline.deliverable import Deliverable, Section, SectionClaim
from src.pipeline.incremental import (
    ClaimTypeRetrievalLayer,
    IncrementalUpdateEngine,
)
from src.pipeline.incremental_api import _build_deliverable_from_run_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run_state_with_claims() -> dict[str, Any]:
    """Simulate a completed run's output_state with claims from a loan agreement.

    The claims array mirrors what the demo_executor produces: ExtractionResult
    dicts with claim_id in the format "doc_type-NNN" or "doc_type.field_idx".
    """
    return {
        "run_id": str(uuid.uuid4()),
        "document_id": str(uuid.uuid4()),
        "claims": [
            {
                "claim_id": "loan_agreement.borrower_name_0",
                "claim_text": "Alice Johnson",
                "confidence": 0.85,
                "citation_status": "grounded",
                "chunk_index": 0,
                "start_offset": 10,
                "end_offset": 23,
            },
            {
                "claim_id": "loan_agreement.interest_rate_1",
                "claim_text": "12.00% per annum",
                "confidence": 0.90,
                "citation_status": "grounded",
                "chunk_index": 0,
                "start_offset": 50,
                "end_offset": 66,
            },
            {
                "claim_id": "loan_agreement.principal_amount_2",
                "claim_text": "50000.00",
                "confidence": 0.92,
                "citation_status": "grounded",
                "chunk_index": 1,
                "start_offset": 0,
                "end_offset": 8,
            },
            {
                "claim_id": "loan_agreement.tenure_months_3",
                "claim_text": "24 months",
                "confidence": 0.88,
                "citation_status": "grounded",
                "chunk_index": 1,
                "start_offset": 20,
                "end_offset": 29,
            },
            {
                "claim_id": "loan_agreement.processing_fee_4",
                "claim_text": "1000.00",
                "confidence": 0.85,
                "citation_status": "grounded",
                "chunk_index": 2,
                "start_offset": 5,
                "end_offset": 12,
            },
        ],
    }


def _build_engine_and_service(run_id: str):
    """Create an IncrementalUpdateEngine with a fresh approval service."""
    store = InMemoryApprovalStore()
    approval_service = ApprovalService(store)
    retrieval_layer = ClaimTypeRetrievalLayer()
    engine = IncrementalUpdateEngine(
        retrieval_layer=retrieval_layer,
        approval_service=approval_service,
        run_id=run_id,
    )
    return engine, approval_service, store


# ---------------------------------------------------------------------------
# Test 1: Hash-identity — unrelated document leaves all existing sections
#          byte-identical (as measured by SHA-256 section hashes).
# ---------------------------------------------------------------------------


class TestIncrementalApiHashIdentity:
    """Prove the hash-identity guarantee through the API's internal path.

    The test simulates what the API endpoint does:
    1. Build deliverable from run state.
    2. Feed new (unrelated) claims through the engine.
    3. Verify all original section hashes are byte-identical.
    """

    def test_unrelated_document_preserves_all_section_hashes(self):
        """Adding a document with claims for new section types leaves
        all existing section hashes unchanged."""
        # Arrange: build deliverable from simulated run state
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)

        # Compute and snapshot hashes BEFORE
        hashes_before = deliverable.compute_all_hashes()
        assert len(hashes_before) == 5  # 5 loan_agreement sections
        for key, h in hashes_before.items():
            assert len(h) == 64  # SHA-256 hex

        # Prepare unrelated claims (repayment_statement — not in existing sections)
        new_doc_id = str(uuid.uuid4())
        unrelated_claims = [
            SectionClaim(
                claim_id="repay-1",
                claim_type="repayment_statement.amount_paid",
                extracted_text="5000.00",
                confidence=0.9,
                source_document_id=new_doc_id,
            ),
            SectionClaim(
                claim_id="repay-2",
                claim_type="repayment_statement.payment_date",
                extracted_text="2024-01-15",
                confidence=0.9,
                source_document_id=new_doc_id,
            ),
        ]

        # Act: run incremental engine
        run_id = run_state["run_id"]
        engine, approval_service, _ = _build_engine_and_service(run_id)
        result = engine.update(
            deliverable=deliverable,
            new_document_claims=unrelated_claims,
            new_document_id=new_doc_id,
        )

        # Compute hashes AFTER
        hashes_after = deliverable.compute_all_hashes()

        # Assert: all original section hashes are byte-identical
        for key, hash_before in hashes_before.items():
            assert key in hashes_after, f"Section {key} disappeared"
            assert hashes_after[key] == hash_before, (
                f"Hash-identity violated for section '{key}'!\n"
                f"  Before: {hash_before}\n"
                f"  After:  {hashes_after[key]}\n"
                "  An unrelated document should NEVER change existing sections."
            )

        # Assert: new sections were added (non-destructive)
        assert "repayment_statement.amount_paid" in hashes_after
        assert "repayment_statement.payment_date" in hashes_after
        assert len(hashes_after) == 7  # 5 original + 2 new

        # Assert: no conflicts
        assert len(result.conflicts) == 0
        assert len(result.approval_items_created) == 0

        # Assert: unaffected sections tracked correctly
        assert result.unaffected_sections == set(hashes_before.keys())

    def test_multiple_unrelated_documents_sequentially_preserve_hashes(self):
        """Adding 3 unrelated documents one after another never alters originals."""
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)
        hashes_before = deliverable.compute_all_hashes()

        run_id = run_state["run_id"]
        engine, _, _ = _build_engine_and_service(run_id)

        # Add 3 unrelated documents sequentially
        for i in range(3):
            new_doc_id = str(uuid.uuid4())
            claims = [
                SectionClaim(
                    claim_id=f"other-{i}",
                    claim_type=f"other_type_{i}.field_x",
                    extracted_text=f"value_{i}",
                    confidence=0.8,
                    source_document_id=new_doc_id,
                ),
            ]
            engine.update(deliverable, claims, new_doc_id)

        hashes_after = deliverable.compute_all_hashes()

        # All original hashes must be preserved
        for key, hash_before in hashes_before.items():
            assert hashes_after[key] == hash_before, (
                f"Section '{key}' hash changed after adding unrelated documents"
            )

    def test_empty_claims_change_nothing(self):
        """A new document that produces zero claims changes nothing."""
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)
        hashes_before = deliverable.compute_all_hashes()

        run_id = run_state["run_id"]
        engine, _, _ = _build_engine_and_service(run_id)

        new_doc_id = str(uuid.uuid4())
        result = engine.update(deliverable, [], new_doc_id)

        hashes_after = deliverable.compute_all_hashes()
        assert hashes_after == hashes_before
        assert len(result.affected_sections) == 0
        assert len(result.conflicts) == 0

    def test_deliverable_hash_itself_unchanged_for_unrelated_sections(self):
        """The full deliverable hash changes (new sections added), but the
        individual section hashes of original sections don't change.

        Note: Adding new sections changes the *deliverable-level* hash
        (it's the hash of all section hashes concatenated). This is correct.
        What must NOT change are the individual section hashes.
        """
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)
        deliverable.compute_all_hashes()
        deliverable_hash_before = deliverable.deliverable_hash
        section_hashes_before = deliverable.get_section_hashes().copy()

        run_id = run_state["run_id"]
        engine, _, _ = _build_engine_and_service(run_id)

        new_doc_id = str(uuid.uuid4())
        engine.update(
            deliverable,
            [SectionClaim(
                claim_id="x",
                claim_type="new_type.field",
                extracted_text="val",
                confidence=0.8,
                source_document_id=new_doc_id,
            )],
            new_doc_id,
        )

        deliverable.compute_all_hashes()

        # Section-level hashes for originals are unchanged
        for key, h in section_hashes_before.items():
            assert deliverable.sections[key].content_hash == h

        # Deliverable-level hash DOES change (new section added)
        assert deliverable.deliverable_hash != deliverable_hash_before


# ---------------------------------------------------------------------------
# Test 2: Contradiction — conflicting document lands in approval queue,
#          deliverable is NOT silently overwritten.
# ---------------------------------------------------------------------------


class TestIncrementalApiContradiction:
    """Prove that contradictions go to approval queue and never auto-apply.

    The test simulates the API's internal path:
    1. Build deliverable from run state.
    2. Feed contradicting claims through the engine.
    3. Verify conflict lands in pending approval queue.
    4. Verify the deliverable section is unchanged.
    """

    def test_contradicting_claim_creates_pending_approval_item(self):
        """A document that contradicts an existing claim → pending approval,
        original value preserved."""
        # Arrange
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)
        hashes_before = deliverable.compute_all_hashes()

        # The existing interest_rate section has "12.00% per annum"
        interest_section = deliverable.sections["loan_agreement.interest_rate"]
        assert interest_section.claims[0].extracted_text == "12.00% per annum"
        interest_hash_before = hashes_before["loan_agreement.interest_rate"]

        # Prepare contradicting claim
        new_doc_id = str(uuid.uuid4())
        conflicting_claims = [
            SectionClaim(
                claim_id="conflict-rate-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="18.00% per annum",  # Contradicts "12.00% per annum"
                confidence=0.85,
                source_document_id=new_doc_id,
            ),
        ]

        # Act
        run_id = run_state["run_id"]
        engine, approval_service, store = _build_engine_and_service(run_id)
        result = engine.update(deliverable, conflicting_claims, new_doc_id)

        # Assert: conflict detected
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.section_key == "loan_agreement.interest_rate"
        assert conflict.existing_claim.extracted_text == "12.00% per annum"
        assert conflict.new_claim.extracted_text == "18.00% per annum"

        # Assert: approval queue item created
        assert len(result.approval_items_created) == 1
        pending = approval_service.get_pending(run_id)
        assert len(pending) == 1
        item = pending[0]
        assert item.status == ItemStatus.PENDING
        assert item.item_type == "conflict"
        assert item.payload["existing_value"] == "12.00% per annum"
        assert item.payload["new_value"] == "18.00% per annum"
        assert item.payload["section_key"] == "loan_agreement.interest_rate"

        # Assert: deliverable NOT changed — hash identical
        hashes_after = deliverable.compute_all_hashes()
        assert hashes_after["loan_agreement.interest_rate"] == interest_hash_before, (
            "Deliverable was silently overwritten! "
            "Conflicts must go to approval queue, not auto-apply."
        )

        # Assert: original value still present
        assert deliverable.sections["loan_agreement.interest_rate"].claims[0].extracted_text == "12.00% per annum"

    def test_contradiction_leaves_other_sections_untouched(self):
        """A contradiction in one section does not affect unrelated sections."""
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)
        hashes_before = deliverable.compute_all_hashes()

        new_doc_id = str(uuid.uuid4())
        # Contradicts interest_rate + adds new unrelated section
        claims = [
            SectionClaim(
                claim_id="c-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="24.00%",
                confidence=0.85,
                source_document_id=new_doc_id,
            ),
            SectionClaim(
                claim_id="new-1",
                claim_type="modification_agreement.effective_date",
                extracted_text="2024-06-01",
                confidence=0.9,
                source_document_id=new_doc_id,
            ),
        ]

        run_id = run_state["run_id"]
        engine, approval_service, _ = _build_engine_and_service(run_id)
        result = engine.update(deliverable, claims, new_doc_id)

        # Conflict detected for interest_rate
        assert len(result.conflicts) == 1
        assert result.conflicts[0].section_key == "loan_agreement.interest_rate"

        # But the new section was added
        assert "modification_agreement.effective_date" in result.sections_updated

        # Original section hashes all preserved
        hashes_after = deliverable.compute_all_hashes()
        for key in hashes_before:
            assert hashes_after[key] == hashes_before[key], (
                f"Section '{key}' was modified despite contradiction being in "
                f"a different section (interest_rate)"
            )

    def test_multiple_contradictions_all_create_approval_items(self):
        """Multiple contradicting claims each create separate approval items."""
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)
        hashes_before = deliverable.compute_all_hashes()

        new_doc_id = str(uuid.uuid4())
        claims = [
            SectionClaim(
                claim_id="c-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="24.00%",
                confidence=0.85,
                source_document_id=new_doc_id,
            ),
            SectionClaim(
                claim_id="c-2",
                claim_type="loan_agreement.principal_amount",
                extracted_text="99999.00",  # Contradicts "50000.00"
                confidence=0.85,
                source_document_id=new_doc_id,
            ),
            SectionClaim(
                claim_id="c-3",
                claim_type="loan_agreement.borrower_name",
                extracted_text="Bob Smith",  # Contradicts "Alice Johnson"
                confidence=0.85,
                source_document_id=new_doc_id,
            ),
        ]

        run_id = run_state["run_id"]
        engine, approval_service, _ = _build_engine_and_service(run_id)
        result = engine.update(deliverable, claims, new_doc_id)

        # All 3 are conflicts
        assert len(result.conflicts) == 3
        assert len(result.approval_items_created) == 3

        # All are pending in the queue
        pending = approval_service.get_pending(run_id)
        assert len(pending) == 3
        assert all(item.status == ItemStatus.PENDING for item in pending)
        assert all(item.item_type == "conflict" for item in pending)

        # All original sections unchanged
        hashes_after = deliverable.compute_all_hashes()
        for key in ["loan_agreement.interest_rate", "loan_agreement.principal_amount", "loan_agreement.borrower_name"]:
            assert hashes_after[key] == hashes_before[key], (
                f"Section '{key}' was silently overwritten despite contradiction!"
            )

    def test_same_value_is_not_a_conflict(self):
        """If the new claim has the same extracted_text, it's not a conflict."""
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)
        hashes_before = deliverable.compute_all_hashes()

        new_doc_id = str(uuid.uuid4())
        # Same value as existing — should NOT be a conflict
        claims = [
            SectionClaim(
                claim_id="confirm-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="12.00% per annum",  # Same as existing
                confidence=0.90,
                source_document_id=new_doc_id,
            ),
        ]

        run_id = run_state["run_id"]
        engine, approval_service, _ = _build_engine_and_service(run_id)
        result = engine.update(deliverable, claims, new_doc_id)

        # No conflicts
        assert len(result.conflicts) == 0
        assert len(result.approval_items_created) == 0

        # Section was updated (merged) — not a conflict
        assert "loan_agreement.interest_rate" in result.sections_updated


# ---------------------------------------------------------------------------
# Test: _build_deliverable_from_run_state correctness
# ---------------------------------------------------------------------------


class TestBuildDeliverableFromRunState:
    """Tests for reconstructing a Deliverable from a run's output state."""

    def test_builds_correct_sections_from_claims(self):
        """Each claim_id with a dot separator produces a properly-keyed section."""
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)

        # Should have 5 sections (one per unique claim_type derived from claim_id)
        assert len(deliverable.sections) == 5
        expected_keys = {
            "loan_agreement.borrower_name",
            "loan_agreement.interest_rate",
            "loan_agreement.principal_amount",
            "loan_agreement.tenure_months",
            "loan_agreement.processing_fee",
        }
        assert deliverable.get_section_keys() == expected_keys

    def test_each_section_has_one_claim(self):
        """Each section in the test data has exactly one claim."""
        run_state = _make_run_state_with_claims()
        deliverable = _build_deliverable_from_run_state(run_state)

        for key, section in deliverable.sections.items():
            assert len(section.claims) == 1, (
                f"Section '{key}' has {len(section.claims)} claims, expected 1"
            )

    def test_hashes_are_deterministic(self):
        """Building the same deliverable twice produces identical hashes."""
        run_state = _make_run_state_with_claims()

        d1 = _build_deliverable_from_run_state(run_state)
        h1 = d1.compute_all_hashes()

        d2 = _build_deliverable_from_run_state(run_state)
        h2 = d2.compute_all_hashes()

        assert h1 == h2

    def test_empty_claims_produces_empty_deliverable(self):
        """A run state with no claims produces an empty deliverable."""
        run_state = {"run_id": "x", "document_id": "y", "claims": []}
        deliverable = _build_deliverable_from_run_state(run_state)
        assert len(deliverable.sections) == 0

    def test_claims_without_dots_get_generic_prefix(self):
        """Claims with IDs lacking dots get a 'generic.' prefix section key."""
        run_state = {
            "run_id": "x",
            "document_id": "y",
            "claims": [
                {
                    "claim_id": "simple-001",
                    "claim_text": "some value",
                    "confidence": 0.7,
                    "citation_status": "grounded",
                }
            ],
        }
        deliverable = _build_deliverable_from_run_state(run_state)
        assert "generic.simple-001" in deliverable.sections
