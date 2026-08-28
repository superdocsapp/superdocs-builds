"""Incremental update engine for focused deliverable updates.

When a new document is dropped into a watched folder, this module determines
which existing sections of the deliverable could plausibly be affected,
re-runs extraction only for those sections, and leaves everything else
byte-identical.

Key guarantees:
1. Unaffected sections remain byte-identical (verifiable via hash comparison).
2. Contradictions between the new document and existing claims are surfaced
   as conflicts in the approval queue — never silently overwritten.
3. Only affected sections are re-processed; no full pipeline re-run.

Conflict detection:
- A contradiction occurs when a new document produces a claim for the same
  section key but with a different extracted_text value than the existing claim.
- Contradictions are routed to the approval queue with item_type="conflict"
  and full context (old value, new value, source documents).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from src.pipeline.approval import (
    ApprovalService,
    ApprovalStore,
    InMemoryApprovalStore,
    ItemStatus,
    QueueItem,
)
from src.pipeline.deliverable import Deliverable, Section, SectionClaim
from src.pipeline.extractors.base import ExtractedFact, SourceSpan


# ---------------------------------------------------------------------------
# Retrieval layer protocol
# ---------------------------------------------------------------------------


class RetrievalLayer(Protocol):
    """Protocol for determining which sections a new document could affect.

    Implementations may use embedding similarity, keyword matching, or
    document-type classification to identify potentially affected sections.
    """

    def find_affected_sections(
        self,
        new_document_claims: list[SectionClaim],
        existing_section_keys: set[str],
    ) -> set[str]:
        """Identify which existing sections the new document could affect.

        Args:
            new_document_claims: Claims extracted from the new document.
            existing_section_keys: All section keys in the current deliverable.

        Returns:
            Set of section keys that could plausibly be affected.
        """
        ...


# ---------------------------------------------------------------------------
# Default retrieval layer: claim-type matching
# ---------------------------------------------------------------------------


class ClaimTypeRetrievalLayer:
    """Retrieval layer that matches by claim_type (section key).

    A new document affects a section if it produces a claim with the same
    claim_type as an existing section. This is the simplest correct approach:
    if the new doc has claims of type X, section X is affected.
    """

    def find_affected_sections(
        self,
        new_document_claims: list[SectionClaim],
        existing_section_keys: set[str],
    ) -> set[str]:
        """Return section keys where new claims overlap with existing sections.

        Args:
            new_document_claims: Claims from the new document.
            existing_section_keys: Keys of all existing sections.

        Returns:
            Intersection of new claim types and existing section keys.
        """
        new_claim_types = {c.claim_type for c in new_document_claims}
        return new_claim_types & existing_section_keys


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


@dataclass
class Conflict:
    """A detected contradiction between existing and new claims.

    Attributes:
        section_key: The section where the conflict was found.
        existing_claim: The claim currently in the deliverable.
        new_claim: The contradicting claim from the new document.
        reason: Human-readable description of the conflict.
    """

    section_key: str
    existing_claim: SectionClaim
    new_claim: SectionClaim
    reason: str


def detect_conflicts(
    existing_section: Section,
    new_claims: list[SectionClaim],
) -> list[Conflict]:
    """Detect contradictions between existing section claims and new claims.

    A conflict is detected when:
    - A new claim has the same claim_type as an existing claim
    - The extracted_text values differ (case-sensitive comparison)
    - Both have confidence > 0 (not "not_found" placeholders)

    Args:
        existing_section: The current section in the deliverable.
        new_claims: Claims from the new document for this section.

    Returns:
        List of Conflict instances (may be empty if no contradictions).
    """
    conflicts: list[Conflict] = []

    # Index existing claims by claim_type for O(1) lookup
    existing_by_type: dict[str, SectionClaim] = {}
    for claim in existing_section.claims:
        existing_by_type[claim.claim_type] = claim

    for new_claim in new_claims:
        existing = existing_by_type.get(new_claim.claim_type)
        if existing is None:
            continue

        # Skip placeholder values
        if existing.extracted_text == "not_found" or new_claim.extracted_text == "not_found":
            continue

        # Conflict: same type, different value
        if existing.extracted_text != new_claim.extracted_text:
            conflicts.append(
                Conflict(
                    section_key=new_claim.claim_type,
                    existing_claim=existing,
                    new_claim=new_claim,
                    reason=(
                        f"Contradicting values for {new_claim.claim_type}: "
                        f"existing='{existing.extracted_text}' vs "
                        f"new='{new_claim.extracted_text}'"
                    ),
                )
            )

    return conflicts


# ---------------------------------------------------------------------------
# Incremental update result
# ---------------------------------------------------------------------------


@dataclass
class IncrementalUpdateResult:
    """Result of an incremental update operation.

    Attributes:
        affected_sections: Section keys that were re-processed.
        unaffected_sections: Section keys left untouched.
        conflicts: Conflicts detected and routed to approval queue.
        sections_updated: Section keys that were successfully updated
            (no conflicts, new claims applied).
        approval_items_created: IDs of approval queue items created for conflicts.
    """

    affected_sections: set[str] = field(default_factory=set)
    unaffected_sections: set[str] = field(default_factory=set)
    conflicts: list[Conflict] = field(default_factory=list)
    sections_updated: set[str] = field(default_factory=set)
    approval_items_created: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Incremental update engine
# ---------------------------------------------------------------------------


class IncrementalUpdateEngine:
    """Performs focused updates to a deliverable when new documents arrive.

    The engine:
    1. Uses the retrieval layer to identify affected sections.
    2. Checks for contradictions in affected sections.
    3. Routes conflicts to the approval queue (never auto-applies).
    4. For non-conflicting affected sections, applies the update.
    5. Leaves unaffected sections byte-identical.

    Args:
        retrieval_layer: Strategy for identifying affected sections.
        approval_service: Service for queuing conflicts for human review.
        run_id: The pipeline run ID for approval queue scoping.
    """

    def __init__(
        self,
        retrieval_layer: RetrievalLayer,
        approval_service: ApprovalService,
        run_id: str,
    ) -> None:
        self._retrieval = retrieval_layer
        self._approval = approval_service
        self._run_id = run_id

    def update(
        self,
        deliverable: Deliverable,
        new_document_claims: list[SectionClaim],
        new_document_id: str,
    ) -> IncrementalUpdateResult:
        """Apply an incremental update from a new document.

        Steps:
        1. Identify affected sections via retrieval layer.
        2. For each affected section, check for conflicts.
        3. If conflicts exist → route to approval queue, do NOT update section.
        4. If no conflicts → update section with merged claims.
        5. Unaffected sections are never touched.

        Args:
            deliverable: The current deliverable to update in place.
            new_document_claims: All claims extracted from the new document.
            new_document_id: UUID string of the new document for provenance.

        Returns:
            IncrementalUpdateResult with full audit of what happened.
        """
        existing_keys = deliverable.get_section_keys()

        # Step 1: Identify affected sections
        affected = self._retrieval.find_affected_sections(
            new_document_claims, existing_keys
        )
        unaffected = existing_keys - affected

        result = IncrementalUpdateResult(
            affected_sections=affected,
            unaffected_sections=unaffected,
        )

        # Group new claims by section key
        new_claims_by_section: dict[str, list[SectionClaim]] = {}
        for claim in new_document_claims:
            key = claim.claim_type
            if key not in new_claims_by_section:
                new_claims_by_section[key] = []
            new_claims_by_section[key].append(claim)

        # Step 2–4: Process each affected section
        for section_key in affected:
            section = deliverable.sections.get(section_key)
            new_claims = new_claims_by_section.get(section_key, [])

            if section is None or not new_claims:
                # Section doesn't exist or no new claims for it — skip
                continue

            # Detect conflicts
            conflicts = detect_conflicts(section, new_claims)

            if conflicts:
                # Step 3: Route to approval queue, do NOT apply
                result.conflicts.extend(conflicts)
                for conflict in conflicts:
                    item = self._approval.enqueue_item(
                        run_id=self._run_id,
                        item_type="conflict",
                        payload={
                            "section_key": conflict.section_key,
                            "existing_claim_id": conflict.existing_claim.claim_id,
                            "existing_value": conflict.existing_claim.extracted_text,
                            "existing_source_document": conflict.existing_claim.source_document_id,
                            "new_claim_id": conflict.new_claim.claim_id,
                            "new_value": conflict.new_claim.extracted_text,
                            "new_source_document": conflict.new_claim.source_document_id,
                            "reason": conflict.reason,
                        },
                    )
                    result.approval_items_created.append(item.id)
            else:
                # Step 4: No conflict — merge new claims into the section
                # Keep existing claims from other documents, add/replace from new doc
                merged_claims = self._merge_claims(section, new_claims, new_document_id)
                deliverable.update_section(section_key, merged_claims)
                result.sections_updated.add(section_key)

        # Handle new sections (claims for keys not yet in deliverable)
        new_only_keys = {c.claim_type for c in new_document_claims} - existing_keys
        for key in new_only_keys:
            claims = new_claims_by_section.get(key, [])
            if claims:
                deliverable.update_section(key, claims)
                result.sections_updated.add(key)

        return result

    def _merge_claims(
        self,
        existing_section: Section,
        new_claims: list[SectionClaim],
        new_document_id: str,
    ) -> list[SectionClaim]:
        """Merge new claims into an existing section.

        Strategy: keep claims from other documents, replace claims from the
        same document, add claims from the new document.

        Args:
            existing_section: Current section with its claims.
            new_claims: New claims to merge in.
            new_document_id: Source document ID for the new claims.

        Returns:
            Merged list of claims for the section.
        """
        # Keep existing claims not from the new document
        kept = [
            c for c in existing_section.claims
            if c.source_document_id != new_document_id
        ]
        # Add all new claims
        kept.extend(new_claims)
        return kept
