"""Deliverable model with section-level hashing for incremental updates.

A Deliverable represents the assembled output of the pipeline — a structured
collection of sections, each backed by one or more claims. Sections are
independently hashable, enabling byte-identity verification after incremental
updates: sections unaffected by a new document must have identical hashes
before and after the update.

Design:
- Each section has a stable key (e.g., "loan_agreement.interest_rate").
- Section content is the canonical serialized form of its claims.
- Section hash is SHA-256 of the canonical content bytes.
- The full deliverable hash is the SHA-256 of all section hashes concatenated
  in sorted key order.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SectionClaim:
    """A single claim within a deliverable section.

    Attributes:
        claim_id: Unique identifier for this claim.
        claim_type: Compound type (e.g., "loan_agreement.interest_rate").
        extracted_text: The extracted value.
        confidence: Confidence score 0.0–1.0.
        source_document_id: Which document this claim came from.
        citation_status: "grounded" if backed by a verified source span,
            "unverifiable" if no source span could be resolved.
    """

    claim_id: str
    claim_type: str
    extracted_text: str
    confidence: float
    source_document_id: str
    citation_status: str = "grounded"  # "grounded" | "unverifiable"


@dataclass
class Section:
    """A single section of the deliverable.

    A section groups claims by type/field. Its hash is computed from the
    canonical JSON serialization of its claims (sorted by claim_id for
    determinism).

    Attributes:
        key: Stable section identifier (e.g., "loan_agreement.interest_rate").
        claims: List of claims in this section.
        content_hash: SHA-256 hex digest of the canonical content.
    """

    key: str
    claims: list[SectionClaim] = field(default_factory=list)
    content_hash: str = ""

    def compute_hash(self) -> str:
        """Compute and store the SHA-256 hash of the section's canonical content.

        Claims are sorted by claim_id for deterministic serialization.
        The hash covers the full claim data (id, type, text, confidence, source).

        Returns:
            The hex digest of the section hash.
        """
        canonical = self._canonical_bytes()
        self.content_hash = hashlib.sha256(canonical).hexdigest()
        return self.content_hash

    def _canonical_bytes(self) -> bytes:
        """Produce deterministic bytes for hashing.

        Claims are sorted by claim_id, then serialized as compact JSON
        with sorted keys to ensure byte-level determinism.
        """
        sorted_claims = sorted(self.claims, key=lambda c: c.claim_id)
        payload = [
            {
                "claim_id": c.claim_id,
                "claim_type": c.claim_type,
                "extracted_text": c.extracted_text,
                "confidence": c.confidence,
                "source_document_id": c.source_document_id,
                "citation_status": c.citation_status,
            }
            for c in sorted_claims
        ]
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class Deliverable:
    """The full pipeline deliverable — a collection of hashed sections.

    Sections are keyed by claim_type. The deliverable hash is the SHA-256
    of all section hashes concatenated in sorted key order.

    Attributes:
        sections: Dict mapping section key to Section instance.
        deliverable_hash: SHA-256 of concatenated section hashes.
    """

    sections: dict[str, Section] = field(default_factory=dict)
    deliverable_hash: str = ""

    def add_claim(self, claim: SectionClaim) -> None:
        """Add a claim to the appropriate section, creating it if needed.

        Args:
            claim: The claim to add to the deliverable.
        """
        key = claim.claim_type
        if key not in self.sections:
            self.sections[key] = Section(key=key)
        self.sections[key].claims.append(claim)

    def update_section(self, key: str, claims: list[SectionClaim]) -> None:
        """Replace the claims in a section entirely.

        Used during incremental update to apply re-extracted claims
        for affected sections only.

        Args:
            key: The section key to update.
            claims: New claims replacing the section content.
        """
        self.sections[key] = Section(key=key, claims=claims)

    def compute_all_hashes(self) -> dict[str, str]:
        """Compute hashes for all sections and the deliverable.

        Returns:
            Dict mapping section key to its content hash.
        """
        section_hashes: dict[str, str] = {}
        for key in sorted(self.sections.keys()):
            section = self.sections[key]
            section.compute_hash()
            section_hashes[key] = section.content_hash

        # Deliverable hash = SHA-256 of all section hashes in sorted key order
        combined = "".join(section_hashes[k] for k in sorted(section_hashes.keys()))
        self.deliverable_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()

        return section_hashes

    def get_section_hashes(self) -> dict[str, str]:
        """Return current section hashes without recomputing.

        Returns:
            Dict mapping section key to its stored content hash.
        """
        return {key: section.content_hash for key, section in self.sections.items()}

    def get_section_keys(self) -> set[str]:
        """Return all section keys in the deliverable.

        Returns:
            Set of section key strings.
        """
        return set(self.sections.keys())
