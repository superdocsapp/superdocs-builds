"""Tests for the watcher and incremental-update stage.

Two key tests proving the invariants:

1. test_unrelated_document_leaves_unaffected_sections_byte_identical:
   Hash the full deliverable before and after adding a new document that
   is unrelated to existing sections. Assert all existing sections' hashes
   are unchanged.

2. test_contradicting_document_lands_in_approval_queue:
   Add a new document that deliberately contradicts an existing claim.
   Assert the conflict lands in the pending-approval queue rather than
   being auto-applied. The original section remains unchanged.
"""

from __future__ import annotations

import os
import tempfile
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
    IncrementalUpdateResult,
    detect_conflicts,
)
from src.pipeline.watcher import FolderWatcher, WatcherEvent


# ---------------------------------------------------------------------------
# Test fixtures and helpers
# ---------------------------------------------------------------------------


class FakeExtractor:
    """Fake extractor that returns pre-configured claims for testing.

    Maps file paths to claim lists. Used to control exactly what claims
    are produced from each "document" without real extraction.
    """

    def __init__(self) -> None:
        self._claims_by_path: dict[str, list[SectionClaim]] = {}

    def register(self, file_path: str, claims: list[SectionClaim]) -> None:
        """Register claims to return for a given file path."""
        self._claims_by_path[file_path] = claims

    def extract_claims(
        self, file_path: str, document_id: str
    ) -> list[SectionClaim]:
        """Return pre-registered claims, updating source_document_id."""
        base_claims = self._claims_by_path.get(file_path, [])
        # Stamp each claim with the assigned document_id
        return [
            SectionClaim(
                claim_id=c.claim_id,
                claim_type=c.claim_type,
                extracted_text=c.extracted_text,
                confidence=c.confidence,
                source_document_id=document_id,
            )
            for c in base_claims
        ]


def _make_deliverable_with_loan_claims() -> tuple[Deliverable, str]:
    """Create a deliverable pre-populated with loan agreement claims.

    Returns:
        Tuple of (deliverable, source_document_id) for the initial doc.
    """
    source_doc_id = str(uuid.uuid4())
    deliverable = Deliverable()

    claims = [
        SectionClaim(
            claim_id="claim-1",
            claim_type="loan_agreement.borrower_name",
            extracted_text="Alice Johnson",
            confidence=0.85,
            source_document_id=source_doc_id,
        ),
        SectionClaim(
            claim_id="claim-2",
            claim_type="loan_agreement.interest_rate",
            extracted_text="12.00",
            confidence=0.85,
            source_document_id=source_doc_id,
        ),
        SectionClaim(
            claim_id="claim-3",
            claim_type="loan_agreement.principal_amount",
            extracted_text="50000.00",
            confidence=0.85,
            source_document_id=source_doc_id,
        ),
        SectionClaim(
            claim_id="claim-4",
            claim_type="loan_agreement.tenure_months",
            extracted_text="24",
            confidence=0.85,
            source_document_id=source_doc_id,
        ),
        SectionClaim(
            claim_id="claim-5",
            claim_type="loan_agreement.processing_fee",
            extracted_text="1000.00",
            confidence=0.85,
            source_document_id=source_doc_id,
        ),
    ]

    for claim in claims:
        deliverable.add_claim(claim)

    deliverable.compute_all_hashes()
    return deliverable, source_doc_id


# ---------------------------------------------------------------------------
# Test 1: Unrelated document leaves unaffected sections byte-identical
# ---------------------------------------------------------------------------


class TestUnrelatedDocumentHashIdentity:
    """Prove that adding an unrelated document never changes unaffected sections.

    The new document produces claims for a section type NOT present in the
    existing deliverable (e.g., "repayment_statement.amount_paid" when the
    deliverable only has "loan_agreement.*" sections). All existing section
    hashes must remain byte-identical.
    """

    def test_unrelated_document_leaves_unaffected_sections_byte_identical(
        self, tmp_path
    ):
        """Hash identity test: unrelated new doc → all existing hashes unchanged.

        Steps:
        1. Build a deliverable with 5 loan_agreement sections, compute hashes.
        2. Snapshot all section hashes.
        3. Drop a new document (repayment statement) into the watched folder.
        4. Run the watcher/incremental update.
        5. Recompute all hashes.
        6. Assert every original section hash is unchanged.
        7. Assert the new section was added (non-destructive).
        """
        # Step 1: Build initial deliverable
        deliverable, original_doc_id = _make_deliverable_with_loan_claims()

        # Step 2: Snapshot hashes BEFORE
        hashes_before = deliverable.compute_all_hashes()
        assert len(hashes_before) == 5  # 5 loan_agreement sections

        # Verify each section has a non-empty hash
        for key, h in hashes_before.items():
            assert len(h) == 64, f"Section {key} hash should be SHA-256 hex"

        # Step 3: Create a new document file in the watch folder
        watch_dir = str(tmp_path / "watched")
        os.makedirs(watch_dir)

        new_doc_path = os.path.join(watch_dir, "repayment_statement_001.txt")
        with open(new_doc_path, "w") as f:
            f.write("Repayment statement: Amount paid 5000.00 on 2024-01-15")

        # Configure extractor to return claims for an UNRELATED section
        extractor = FakeExtractor()
        unrelated_claims = [
            SectionClaim(
                claim_id="new-claim-1",
                claim_type="repayment_statement.amount_paid",
                extracted_text="5000.00",
                confidence=0.9,
                source_document_id="",  # Will be stamped by extractor
            ),
            SectionClaim(
                claim_id="new-claim-2",
                claim_type="repayment_statement.payment_date",
                extracted_text="2024-01-15",
                confidence=0.9,
                source_document_id="",
            ),
        ]
        extractor.register(new_doc_path, unrelated_claims)

        # Step 4: Create watcher and scan
        watcher = FolderWatcher(
            watch_dir=watch_dir,
            deliverable=deliverable,
            extractor=extractor,
        )
        events = watcher.scan()

        # Verify the file was processed
        assert len(events) == 1
        assert events[0].error is None
        assert events[0].update_result is not None

        # Verify no conflicts were detected
        result = events[0].update_result
        assert len(result.conflicts) == 0

        # Step 5: Recompute all hashes AFTER
        hashes_after = deliverable.compute_all_hashes()

        # Step 6: Assert ALL original section hashes are unchanged
        for key, hash_before in hashes_before.items():
            assert key in hashes_after, (
                f"Section {key} disappeared after incremental update"
            )
            assert hashes_after[key] == hash_before, (
                f"Section {key} hash changed after adding unrelated document!\n"
                f"  Before: {hash_before}\n"
                f"  After:  {hashes_after[key]}"
            )

        # Step 7: Verify new sections were added (non-destructive)
        assert "repayment_statement.amount_paid" in hashes_after
        assert "repayment_statement.payment_date" in hashes_after
        assert len(hashes_after) == 7  # 5 original + 2 new

    def test_multiple_unrelated_documents_preserve_all_hashes(self, tmp_path):
        """Adding multiple unrelated documents preserves all original hashes."""
        deliverable, _ = _make_deliverable_with_loan_claims()
        hashes_before = deliverable.compute_all_hashes()

        watch_dir = str(tmp_path / "watched")
        os.makedirs(watch_dir)

        extractor = FakeExtractor()

        # Create 3 unrelated documents
        for i in range(3):
            path = os.path.join(watch_dir, f"unrelated_{i}.txt")
            with open(path, "w") as f:
                f.write(f"Unrelated content {i} with unique data {uuid.uuid4()}")
            extractor.register(
                path,
                [
                    SectionClaim(
                        claim_id=f"uc-{i}",
                        claim_type=f"other_doc_type.field_{i}",
                        extracted_text=f"value_{i}",
                        confidence=0.8,
                        source_document_id="",
                    )
                ],
            )

        watcher = FolderWatcher(
            watch_dir=watch_dir,
            deliverable=deliverable,
            extractor=extractor,
        )
        events = watcher.scan()
        assert len(events) == 3

        # Recompute and verify
        hashes_after = deliverable.compute_all_hashes()
        for key, hash_before in hashes_before.items():
            assert hashes_after[key] == hash_before, (
                f"Section {key} changed after adding unrelated documents"
            )

    def test_empty_new_document_changes_nothing(self, tmp_path):
        """A new document with no extractable claims changes nothing."""
        deliverable, _ = _make_deliverable_with_loan_claims()
        hashes_before = deliverable.compute_all_hashes()

        watch_dir = str(tmp_path / "watched")
        os.makedirs(watch_dir)

        path = os.path.join(watch_dir, "empty_doc.txt")
        with open(path, "w") as f:
            f.write("This document has no extractable claims.")

        extractor = FakeExtractor()
        extractor.register(path, [])  # No claims

        watcher = FolderWatcher(
            watch_dir=watch_dir,
            deliverable=deliverable,
            extractor=extractor,
        )
        events = watcher.scan()

        hashes_after = deliverable.compute_all_hashes()
        assert hashes_after == hashes_before


# ---------------------------------------------------------------------------
# Test 2: Contradicting document lands in approval queue
# ---------------------------------------------------------------------------


class TestContradictionGoesToApprovalQueue:
    """Prove that contradictions are surfaced as conflicts, never auto-applied.

    When a new document produces a claim that contradicts an existing claim
    (same claim_type, different extracted_text), the conflict must land in
    the pending-approval queue. The original section must remain unchanged.
    """

    def test_contradicting_document_lands_in_approval_queue(self, tmp_path):
        """Conflict test: contradicting new doc → pending approval queue.

        Steps:
        1. Build a deliverable with interest_rate = "12.00".
        2. Snapshot the interest_rate section hash.
        3. Drop a new document claiming interest_rate = "18.00" (contradiction).
        4. Run the watcher/incremental update.
        5. Assert a conflict was detected.
        6. Assert the conflict is in the approval queue with status "pending".
        7. Assert the original section hash is UNCHANGED (not overwritten).
        8. Assert the deliverable still shows "12.00" (original value preserved).
        """
        # Step 1: Build initial deliverable
        deliverable, original_doc_id = _make_deliverable_with_loan_claims()

        # Step 2: Snapshot hash of the section that will be contradicted
        hashes_before = deliverable.compute_all_hashes()
        interest_rate_hash_before = hashes_before["loan_agreement.interest_rate"]

        # Step 3: Create contradicting document
        watch_dir = str(tmp_path / "watched")
        os.makedirs(watch_dir)

        contradicting_path = os.path.join(watch_dir, "modification_agreement.txt")
        with open(contradicting_path, "w") as f:
            f.write("Modification: interest rate changed to 18%")

        extractor = FakeExtractor()
        contradicting_claims = [
            SectionClaim(
                claim_id="conflict-claim-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="18.00",  # Contradicts existing "12.00"
                confidence=0.85,
                source_document_id="",
            ),
        ]
        extractor.register(contradicting_path, contradicting_claims)

        # Step 4: Create watcher with explicit approval store for inspection
        approval_store = InMemoryApprovalStore()
        approval_service = ApprovalService(approval_store)
        run_id = str(uuid.uuid4())

        watcher = FolderWatcher(
            watch_dir=watch_dir,
            deliverable=deliverable,
            extractor=extractor,
            approval_service=approval_service,
            run_id=run_id,
        )
        events = watcher.scan()

        # Verify file was processed
        assert len(events) == 1
        assert events[0].error is None
        result = events[0].update_result
        assert result is not None

        # Step 5: Assert a conflict was detected
        assert len(result.conflicts) == 1
        conflict = result.conflicts[0]
        assert conflict.section_key == "loan_agreement.interest_rate"
        assert conflict.existing_claim.extracted_text == "12.00"
        assert conflict.new_claim.extracted_text == "18.00"

        # Step 6: Assert the conflict is in the approval queue
        pending_items = approval_service.get_pending(run_id)
        assert len(pending_items) == 1

        queue_item = pending_items[0]
        assert queue_item.status == ItemStatus.PENDING
        assert queue_item.item_type == "conflict"
        assert queue_item.payload["section_key"] == "loan_agreement.interest_rate"
        assert queue_item.payload["existing_value"] == "12.00"
        assert queue_item.payload["new_value"] == "18.00"
        assert "reason" in queue_item.payload

        # Step 7: Assert the original section hash is UNCHANGED
        hashes_after = deliverable.compute_all_hashes()
        assert hashes_after["loan_agreement.interest_rate"] == interest_rate_hash_before, (
            "Section hash changed despite conflict — value was silently overwritten!"
        )

        # Step 8: Assert deliverable still shows original value
        interest_section = deliverable.sections["loan_agreement.interest_rate"]
        assert len(interest_section.claims) == 1
        assert interest_section.claims[0].extracted_text == "12.00"

    def test_contradiction_does_not_affect_other_sections(self, tmp_path):
        """A contradicting doc only blocks the conflicting section, not others.

        If a new doc contradicts section A but has non-conflicting claims for
        section B, section B should still be updated normally.
        """
        deliverable, original_doc_id = _make_deliverable_with_loan_claims()
        hashes_before = deliverable.compute_all_hashes()

        watch_dir = str(tmp_path / "watched")
        os.makedirs(watch_dir)

        path = os.path.join(watch_dir, "mixed_doc.txt")
        with open(path, "w") as f:
            f.write("Mixed content")

        extractor = FakeExtractor()
        # One contradicting claim + one claim for a new section
        mixed_claims = [
            SectionClaim(
                claim_id="conflict-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="24.00",  # Contradicts existing "12.00"
                confidence=0.85,
                source_document_id="",
            ),
            SectionClaim(
                claim_id="new-section-1",
                claim_type="modification_agreement.effective_date",
                extracted_text="2024-06-01",
                confidence=0.9,
                source_document_id="",
            ),
        ]
        extractor.register(path, mixed_claims)

        approval_store = InMemoryApprovalStore()
        approval_service = ApprovalService(approval_store)
        run_id = str(uuid.uuid4())

        watcher = FolderWatcher(
            watch_dir=watch_dir,
            deliverable=deliverable,
            extractor=extractor,
            approval_service=approval_service,
            run_id=run_id,
        )
        events = watcher.scan()
        result = events[0].update_result

        # Conflict detected for interest_rate
        assert len(result.conflicts) == 1
        assert result.conflicts[0].section_key == "loan_agreement.interest_rate"

        # But the new section was still added
        assert "modification_agreement.effective_date" in result.sections_updated

        # Original sections unchanged
        hashes_after = deliverable.compute_all_hashes()
        assert hashes_after["loan_agreement.interest_rate"] == hashes_before["loan_agreement.interest_rate"]

        # New section exists
        assert "modification_agreement.effective_date" in deliverable.sections

    def test_multiple_contradictions_all_go_to_queue(self, tmp_path):
        """Multiple contradictions in one document all land in the queue."""
        deliverable, _ = _make_deliverable_with_loan_claims()

        watch_dir = str(tmp_path / "watched")
        os.makedirs(watch_dir)

        path = os.path.join(watch_dir, "full_contradiction.txt")
        with open(path, "w") as f:
            f.write("Full contradiction document")

        extractor = FakeExtractor()
        contradicting_claims = [
            SectionClaim(
                claim_id="c-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="24.00",
                confidence=0.85,
                source_document_id="",
            ),
            SectionClaim(
                claim_id="c-2",
                claim_type="loan_agreement.principal_amount",
                extracted_text="100000.00",  # Contradicts "50000.00"
                confidence=0.85,
                source_document_id="",
            ),
            SectionClaim(
                claim_id="c-3",
                claim_type="loan_agreement.borrower_name",
                extracted_text="Bob Smith",  # Contradicts "Alice Johnson"
                confidence=0.85,
                source_document_id="",
            ),
        ]
        extractor.register(path, contradicting_claims)

        approval_store = InMemoryApprovalStore()
        approval_service = ApprovalService(approval_store)
        run_id = str(uuid.uuid4())

        watcher = FolderWatcher(
            watch_dir=watch_dir,
            deliverable=deliverable,
            extractor=extractor,
            approval_service=approval_service,
            run_id=run_id,
        )
        events = watcher.scan()
        result = events[0].update_result

        # All 3 contradictions detected
        assert len(result.conflicts) == 3

        # All 3 are in the approval queue
        pending = approval_service.get_pending(run_id)
        assert len(pending) == 3
        assert all(item.status == ItemStatus.PENDING for item in pending)
        assert all(item.item_type == "conflict" for item in pending)


# ---------------------------------------------------------------------------
# Additional tests for incremental engine correctness
# ---------------------------------------------------------------------------


class TestIncrementalEngineEdgeCases:
    """Additional edge case coverage for the incremental update engine."""

    def test_same_value_is_not_a_conflict(self):
        """A new claim with the same value as existing is NOT a conflict."""
        deliverable, original_doc_id = _make_deliverable_with_loan_claims()
        hashes_before = deliverable.compute_all_hashes()

        approval_store = InMemoryApprovalStore()
        approval_service = ApprovalService(approval_store)
        run_id = str(uuid.uuid4())

        engine = IncrementalUpdateEngine(
            retrieval_layer=ClaimTypeRetrievalLayer(),
            approval_service=approval_service,
            run_id=run_id,
        )

        # Same value as existing — should NOT be a conflict
        new_claims = [
            SectionClaim(
                claim_id="confirm-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="12.00",  # Same as existing!
                confidence=0.9,
                source_document_id=str(uuid.uuid4()),
            ),
        ]

        result = engine.update(deliverable, new_claims, str(uuid.uuid4()))

        # No conflicts
        assert len(result.conflicts) == 0
        # Section was updated (merged, not conflicted)
        assert "loan_agreement.interest_rate" in result.sections_updated

        # No items in approval queue
        pending = approval_service.get_pending(run_id)
        assert len(pending) == 0

    def test_not_found_values_are_not_conflicts(self):
        """Placeholder 'not_found' values never trigger conflicts."""
        deliverable = Deliverable()
        deliverable.add_claim(
            SectionClaim(
                claim_id="existing-1",
                claim_type="loan_agreement.penal_rate",
                extracted_text="not_found",
                confidence=0.0,
                source_document_id=str(uuid.uuid4()),
            )
        )
        deliverable.compute_all_hashes()

        approval_store = InMemoryApprovalStore()
        approval_service = ApprovalService(approval_store)
        run_id = str(uuid.uuid4())

        engine = IncrementalUpdateEngine(
            retrieval_layer=ClaimTypeRetrievalLayer(),
            approval_service=approval_service,
            run_id=run_id,
        )

        new_claims = [
            SectionClaim(
                claim_id="new-1",
                claim_type="loan_agreement.penal_rate",
                extracted_text="5.00",  # Fills in previously not_found
                confidence=0.85,
                source_document_id=str(uuid.uuid4()),
            ),
        ]

        result = engine.update(deliverable, new_claims, str(uuid.uuid4()))

        # Not a conflict — "not_found" is a placeholder
        assert len(result.conflicts) == 0
        assert "loan_agreement.penal_rate" in result.sections_updated

    def test_detect_conflicts_function_directly(self):
        """Unit test for the detect_conflicts function."""
        existing = Section(
            key="loan_agreement.interest_rate",
            claims=[
                SectionClaim(
                    claim_id="e-1",
                    claim_type="loan_agreement.interest_rate",
                    extracted_text="12.00",
                    confidence=0.85,
                    source_document_id="doc-1",
                ),
            ],
        )

        new_claims = [
            SectionClaim(
                claim_id="n-1",
                claim_type="loan_agreement.interest_rate",
                extracted_text="18.00",
                confidence=0.85,
                source_document_id="doc-2",
            ),
        ]

        conflicts = detect_conflicts(existing, new_claims)
        assert len(conflicts) == 1
        assert conflicts[0].existing_claim.extracted_text == "12.00"
        assert conflicts[0].new_claim.extracted_text == "18.00"
        assert "loan_agreement.interest_rate" in conflicts[0].reason
