"""Shared case -> API-schema conversion, used by intake/analysis/review routes."""

from __future__ import annotations

import re

from app.backend.schemas import CaseSummaryOut, RateChangeOut
from src.amendment_case import AmendmentCase

_HEADING_MARKUP_RE = re.compile(r"^#{1,6}\s*")


def _clean_clause_reference(raw: str | None) -> str:
    """Strip leading Markdown heading markup ('## Article 7 — ...' -> 'Article 7 — ...')."""

    if not raw:
        return "the applicable amendment clause"
    return _HEADING_MARKUP_RE.sub("", raw).strip()


def render_amendment_letter(case: AmendmentCase) -> str:
    letter_data = case.analysis.amendment_letter_data
    if letter_data.blocked:
        return f"(amendment letter withheld: {letter_data.blocked_reason})"

    changed = [c for c in case.proposed_changes if c.new_rate_usd_per_min is not None]
    rate_lines = "\n".join(
        f"| {c.destination} | {c.old_rate_usd_per_min} | {c.new_rate_usd_per_min} |" for c in changed
    )
    clause_reference = _clean_clause_reference(letter_data.amendment_clause_reference)
    rate_schedule_reference = letter_data.rate_schedule_reference or "the current rate schedule referenced in the Agreement"

    return (
        f"# Rate Amendment Notice\n\n"
        f"**To:** {letter_data.partner_legal_name}\n"
        f"**From:** {letter_data.our_legal_name}\n"
        f"**Re:** Notice of Rate Amendment under Agreement {letter_data.contract_identifier}, "
        f"dated {letter_data.contract_date}\n\n"
        f"Pursuant to {clause_reference}, this letter constitutes formal "
        f"written notice of a proposed amendment to the rates set forth in "
        f"{rate_schedule_reference}.\n\n"
        f"Required notice period: {letter_data.required_notice_period_days} days "
        f"(delivery method: {letter_data.notice_delivery_method}).\n\n"
        f"| Destination | Current Rate (USD/min) | Proposed Rate (USD/min) |\n"
        f"|---|---|---|\n"
        f"{rate_lines}\n"
    )


def to_case_summary(case: AmendmentCase) -> CaseSummaryOut:
    analysis = case.analysis
    eligibility = analysis.eligibility
    pricing_clause = analysis.pricing_clause

    return CaseSummaryOut(
        case_id=case.case_id,
        partner_name=analysis.partner_contract.partner_name,
        contract_identifier=analysis.partner_contract.contract_identifier,
        state=case.state.value,
        eligibility_status=eligibility.status.value,
        blocking_reason=case.blocking_reason,
        amendment_mechanism=eligibility.amendment_mechanism,
        pricing_lock_active=eligibility.pricing_lock_active,
        mutual_consent_required=eligibility.mutual_consent_required,
        requires_human_escalation=eligibility.requires_human_escalation,
        prompt_injection_present=eligibility.prompt_injection_present,
        notice_period_days=analysis.notice.notice_period_days,
        notice_period_type=analysis.notice.notice_period_type,
        pricing_clause_reference=pricing_clause.clause_reference if pricing_clause else None,
        pricing_clause_citation=pricing_clause.citation.source_span if pricing_clause else None,
        confidence=analysis.partner_contract.citation.confidence,
        proposed_rate_changes=[
            RateChangeOut(
                destination=c.destination,
                old_rate_usd_per_min=c.old_rate_usd_per_min,
                new_rate_usd_per_min=c.new_rate_usd_per_min,
                change_pct=c.change_pct,
                source_citation=c.citation.source_span,
            )
            for c in case.proposed_changes
        ],
        failure=None if case.failure is None else case.failure.to_dict(),
    )
