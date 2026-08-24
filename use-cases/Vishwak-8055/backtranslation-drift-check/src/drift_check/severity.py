"""Severity and review-status policy.

Two independent questions get answered here, and it matters that they stay
independent:

1. **How severe is this finding?** Decided on the merits of the signal
   (deterministic rule or semantic assessment) that produced it. A
   semantic-only finding is not down-graded just because no regex caught it
   — see DECISIONS.md #4 for why suppressing severity would itself be a
   safety problem (a reviewer triaging by severity could skip a genuinely
   critical issue that only the AI layer saw).

2. **How much scrutiny does this finding need before a correction can be
   approved?** This is where "the LLM must not be the sole authority" is
   actually enforced: findings with no deterministic corroboration, or with
   uncertain section alignment, start in ``REVIEW_REQUIRED`` rather than the
   standard ``PENDING_REVIEW`` queue. Every finding requires an explicit
   human decision before any correction is applied, regardless of severity
   or provenance — REVIEW_REQUIRED is a stronger flag, not a gate that
   PENDING_REVIEW lacks.
"""

from __future__ import annotations

from drift_check.models import ReviewStatus, Severity


def combine_severity(a: Severity, b: Severity) -> Severity:
    """Return the higher-ranked of two severities."""
    return a if a.rank >= b.rank else b


def initial_review_status(
    *,
    verified_deterministically: bool,
    alignment_review_required: bool,
    confidence: float,
    low_confidence_threshold: float = 0.5,
) -> ReviewStatus:
    if alignment_review_required:
        return ReviewStatus.REVIEW_REQUIRED
    if not verified_deterministically:
        return ReviewStatus.REVIEW_REQUIRED
    if confidence < low_confidence_threshold:
        return ReviewStatus.REVIEW_REQUIRED
    return ReviewStatus.PENDING_REVIEW
