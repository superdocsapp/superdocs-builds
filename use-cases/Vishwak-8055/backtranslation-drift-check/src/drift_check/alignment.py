"""Section alignment between a source document and its translation.

This module makes no claim to semantic alignment. It aligns sections
positionally, which is reliable exactly when the translator preserved
section order and count (true for the overwhelming majority of real
localization workflows, where translation tools operate segment-by-segment
inside the original structure).

When that assumption doesn't hold — section counts differ — alignment falls
back to pairing what it can by position and marks every pair, and any
unmatched section, as ``review_required``. It never guesses a semantic
correspondence between out-of-order sections. See DECISIONS.md #3.
"""

from __future__ import annotations

from drift_check.models import Document, SectionPair


def align_sections(source: Document, target: Document) -> list[SectionPair]:
    pairs: list[SectionPair] = []
    n_source = len(source.sections)
    n_target = len(target.sections)

    if n_source == 0 or n_target == 0:
        reason = "source has no sections" if n_source == 0 else "translation has no sections"
        for s in source.sections:
            pairs.append(
                SectionPair(
                    source_section_id=s.id,
                    target_section_id="",
                    alignment_confidence=0.0,
                    review_required=True,
                    reason=reason,
                )
            )
        return pairs

    if n_source == n_target:
        for s, t in zip(source.sections, target.sections, strict=True):
            pairs.append(
                SectionPair(
                    source_section_id=s.id,
                    target_section_id=t.id,
                    alignment_confidence=1.0,
                    review_required=False,
                    reason=None,
                )
            )
        return pairs

    # Count mismatch: pair by position as far as it goes, flag everything as
    # review-required, and record unmatched sections on whichever side is
    # longer so nothing is silently dropped from the audit trail.
    reason = f"section count mismatch: source has {n_source}, translation has {n_target}"
    common = min(n_source, n_target)
    for i in range(common):
        s, t = source.sections[i], target.sections[i]
        pairs.append(
            SectionPair(
                source_section_id=s.id,
                target_section_id=t.id,
                alignment_confidence=0.4,
                review_required=True,
                reason=reason,
            )
        )
    for s in source.sections[common:]:
        pairs.append(
            SectionPair(
                source_section_id=s.id,
                target_section_id="",
                alignment_confidence=0.0,
                review_required=True,
                reason=reason + " (unmatched source section)",
            )
        )
    for t in target.sections[common:]:
        pairs.append(
            SectionPair(
                source_section_id="",
                target_section_id=t.id,
                alignment_confidence=0.0,
                review_required=True,
                reason=reason + " (unmatched translation section)",
            )
        )
    return pairs
