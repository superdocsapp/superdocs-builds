"""Step 12: eligibility decision.

This is the single deterministic decision procedure mirroring
`fixtures/playbooks/contract_review_playbook.md` §3. It composes the outputs
of steps 8-11 (pricing lock, mutual consent, effective-date validation,
conflicts) and never itself re-derives facts from raw text — it only
combines already-extracted, cited facts. This keeps rule execution separate
from model reasoning: nothing here calls a model, and nothing here can be
overridden by document content (including the embedded prompt-injection
string, which surfaces only as a `Conflict`/reviewer-note fact, never as a
branch condition here).

Low-confidence or conflicted inputs always fall through to
`requires_review`, and pricing-lock / mutual-consent outcomes are terminal:
they can never be reinterpreted downstream into an eligible determination.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from src.domain.models import (
    Conflict,
    EligibilityDecision,
    EligibilityStatus,
    ExtractionMethod,
    NoticeRequirement,
    SourceCitation,
)
from src.rules.conflicts import detect_conflicts, has_prompt_injection
from src.rules.effective_date import validate_effective_date
from src.rules.mutual_consent import detect_mutual_consent
from src.rules.pricing_lock import detect_pricing_lock

_CONFIDENCE_REVIEW_THRESHOLD = 0.5


def decide_eligibility(
    document_id: str,
    text: str,
    notice: NoticeRequirement,
    reference_date: date,
) -> EligibilityDecision:
    """Step 12: combine steps 8-11 into a single eligibility determination."""

    conflicts: list[Conflict] = detect_conflicts(document_id, text)
    prompt_injection_present = has_prompt_injection(text)
    lock = detect_pricing_lock(text, reference_date)
    consent = detect_mutual_consent(text)
    effective_date = validate_effective_date(text)

    citations: list[SourceCitation] = [notice.citation]
    for conflict in conflicts:
        citations.append(conflict.citation)

    # Escalation: unresolved conflicts, unattached-document dependencies, or
    # an undeterminable effective-date rule always win over every other
    # branch — mirrors playbook §4 escalation triggers, which are
    # non-negotiable regardless of what else the document appears to say.
    non_injection_conflicts = [
        c for c in conflicts if "embedded instruction-like text" not in c.description
    ]
    if non_injection_conflicts or not effective_date.determinable:
        reasons = "; ".join(c.description for c in non_injection_conflicts)
        return EligibilityDecision(
            document_id=document_id,
            status=EligibilityStatus.REQUIRES_REVIEW,
            amendment_mechanism="indeterminate from the attached document",
            exclusion_reason=f"ambiguous contract: {reasons}" if reasons else "effective-date rule not determinable from attached document",
            pricing_lock_active=lock.active,
            mutual_consent_required=None,
            requires_human_escalation=True,
            citations=tuple(citations),
            prompt_injection_present=prompt_injection_present,
            prompt_injection_note=(
                "embedded instruction-like text detected and logged as contract "
                "data only; not treated as an instruction and not used to justify "
                "approval"
                if prompt_injection_present
                else None
            ),
        )

    # Pricing lock: terminal, never produces a contract edit.
    if lock.active:
        return EligibilityDecision(
            document_id=document_id,
            status=EligibilityStatus.NOT_ELIGIBLE,
            amendment_mechanism="locked until Lock Period expiry; notice-with-affirmative-acceptance thereafter",
            exclusion_reason=f"active pricing lock in effect until {lock.expiry}; evaluation reference date is within the Lock Period",
            pricing_lock_active=True,
            mutual_consent_required=False,
            requires_human_escalation=False,
            citations=tuple(citations),
        )

    # Mutual consent: terminal, never produces a unilateral amendment letter.
    if consent.required:
        return EligibilityDecision(
            document_id=document_id,
            status=EligibilityStatus.NOT_ELIGIBLE_UNILATERALLY,
            amendment_mechanism="mutual written consent required; unilateral notice has no binding effect",
            exclusion_reason="mutual written consent required; notice alone cannot effect an amendment",
            pricing_lock_active=False,
            mutual_consent_required=True,
            requires_human_escalation=False,
            citations=tuple(citations),
        )

    # Low-confidence notice extraction: escalate rather than guess.
    if notice.citation.confidence < _CONFIDENCE_REVIEW_THRESHOLD:
        return EligibilityDecision(
            document_id=document_id,
            status=EligibilityStatus.REQUIRES_REVIEW,
            amendment_mechanism="indeterminate from the attached document",
            exclusion_reason="low-confidence notice-period extraction; human review required",
            pricing_lock_active=False,
            mutual_consent_required=False,
            requires_human_escalation=True,
            citations=tuple(citations),
        )

    return EligibilityDecision(
        document_id=document_id,
        status=EligibilityStatus.ELIGIBLE,
        amendment_mechanism="notice-only, no countersignature required",
        exclusion_reason=None,
        pricing_lock_active=False,
        mutual_consent_required=False,
        requires_human_escalation=False,
        citations=tuple(citations),
    )
