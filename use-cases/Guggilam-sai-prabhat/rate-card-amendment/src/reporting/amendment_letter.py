"""Step 13: amendment-letter data preparation.

Populates the fields needed to fill in
`fixtures/templates/amendment_letter_template.md`. Per the non-negotiable
rule that pricing-lock and mutual-consent (and escalation) cases must never
generate a contract edit, this function returns a `blocked=True`
`AmendmentLetterData` for any status other than `EligibilityStatus.ELIGIBLE`,
with every proposal-specific field left `None`.
"""

from __future__ import annotations

from src.domain.models import (
    AmendmentLetterData,
    EligibilityDecision,
    EligibilityStatus,
    ExtractionMethod,
    NoticeRequirement,
    PartnerContract,
    PricingClause,
    SourceCitation,
)


def prepare_amendment_letter_data(
    partner_contract: PartnerContract,
    pricing_clause: PricingClause | None,
    notice: NoticeRequirement,
    eligibility: EligibilityDecision,
) -> AmendmentLetterData:
    """Step 13: prepare amendment-letter template fields, or block generation."""

    if eligibility.status != EligibilityStatus.ELIGIBLE:
        return AmendmentLetterData(
            document_id=partner_contract.document_id,
            partner_legal_name=None,
            our_legal_name=None,
            contract_identifier=None,
            contract_date=None,
            amendment_clause_reference=None,
            rate_schedule_reference=None,
            required_notice_period_days=None,
            notice_delivery_method=None,
            blocked=True,
            blocked_reason=(
                f"eligibility status is '{eligibility.status.value}', not 'eligible'; "
                f"reason: {eligibility.exclusion_reason}"
            ),
            citation=SourceCitation(
                document_id=partner_contract.document_id,
                source_span=eligibility.exclusion_reason or "not eligible",
                confidence=1.0,
                extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
            ),
        )

    return AmendmentLetterData(
        document_id=partner_contract.document_id,
        partner_legal_name=partner_contract.partner_name,
        our_legal_name=partner_contract.our_entity,
        contract_identifier=partner_contract.contract_identifier,
        contract_date=partner_contract.contract_date,
        amendment_clause_reference=pricing_clause.clause_reference if pricing_clause else None,
        rate_schedule_reference=pricing_clause.current_rates_reference if pricing_clause else None,
        required_notice_period_days=notice.notice_period_days,
        notice_delivery_method=notice.delivery_method,
        blocked=False,
        blocked_reason=None,
        citation=SourceCitation(
            document_id=partner_contract.document_id,
            source_span=pricing_clause.citation.source_span if pricing_clause else "",
            confidence=0.85,
            extraction_method=ExtractionMethod.DETERMINISTIC_RULE,
        ),
    )
