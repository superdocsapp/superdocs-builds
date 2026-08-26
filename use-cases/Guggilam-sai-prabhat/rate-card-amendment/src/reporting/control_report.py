"""Step 14: control-report generation.

Aggregates one `ControlReportRow` per contract for a corpus-wide control
report, suitable for spot-checking that eligibility outcomes and escalation
flags are as expected across the whole book of contracts.
"""

from __future__ import annotations

from src.domain.models import Conflict, ControlReportRow, EligibilityDecision, PartnerContract


def generate_control_report(
    rows: list[tuple[PartnerContract, EligibilityDecision, list[Conflict]]]
) -> list[ControlReportRow]:
    """Step 14: build the aggregate control report across the corpus."""

    return [
        ControlReportRow(
            document_id=partner_contract.document_id,
            partner_name=partner_contract.partner_name,
            contract_identifier=partner_contract.contract_identifier,
            eligibility_status=eligibility.status,
            amendment_mechanism=eligibility.amendment_mechanism,
            pricing_lock_active=eligibility.pricing_lock_active,
            mutual_consent_required=eligibility.mutual_consent_required,
            requires_human_escalation=eligibility.requires_human_escalation,
            prompt_injection_present=eligibility.prompt_injection_present,
            open_conflicts=len(conflicts),
        )
        for partner_contract, eligibility, conflicts in rows
    ]
