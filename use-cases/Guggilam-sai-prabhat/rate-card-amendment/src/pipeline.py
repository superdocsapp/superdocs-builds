"""Orchestrates the 14-step pipeline over a single contract document.

This is the one place all steps are wired together; each step function
itself remains independently importable and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.domain.models import (
    AmendmentLetterData,
    Conflict,
    DocumentType,
    EligibilityDecision,
    NoticeRequirement,
    PartnerContract,
    PricingClause,
)
from src.extraction.classification import classify_document
from src.extraction.clauses import extract_pricing_clause
from src.extraction.metadata import extract_partner_contract
from src.extraction.text_extraction import extract_document_text
from src.reporting.amendment_letter import prepare_amendment_letter_data
from src.rules.conflicts import detect_conflicts
from src.rules.eligibility import decide_eligibility
from src.rules.notice_period import extract_notice_requirement


@dataclass(frozen=True)
class ContractAnalysis:
    document_id: str
    document_type: DocumentType
    partner_contract: PartnerContract
    pricing_clause: PricingClause | None
    notice: NoticeRequirement
    conflicts: list[Conflict]
    eligibility: EligibilityDecision
    amendment_letter_data: AmendmentLetterData


def analyze_contract(file_path: str, reference_date: date) -> ContractAnalysis:
    """Run steps 1-13 over a single contract file."""

    text = extract_document_text(file_path)
    document_type = classify_document(file_path, text)

    partner_contract = extract_partner_contract(file_path, text)
    pricing_clause = extract_pricing_clause(
        file_path,
        text,
        current_rates_reference=None,
    )
    notice = extract_notice_requirement(file_path, text)
    conflicts = detect_conflicts(file_path, text)
    eligibility = decide_eligibility(file_path, text, notice, reference_date)
    amendment_letter_data = prepare_amendment_letter_data(
        partner_contract, pricing_clause, notice, eligibility
    )

    return ContractAnalysis(
        document_id=file_path,
        document_type=document_type,
        partner_contract=partner_contract,
        pricing_clause=pricing_clause,
        notice=notice,
        conflicts=conflicts,
        eligibility=eligibility,
        amendment_letter_data=amendment_letter_data,
    )
