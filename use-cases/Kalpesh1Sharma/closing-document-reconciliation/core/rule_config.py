from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.models import DocumentType


SourceKind = Literal["field", "fee"]
TextSemantics = Literal[
    "middle_initial_omission",
    "address_abbreviations",
]


@dataclass(frozen=True)
class NumericReconciliationConfig:
    field_name: str
    source_key: str
    source_kind: SourceKind
    observation_documents: tuple[DocumentType, ...]
    reference_document: DocumentType
    rule_id: str | None
    curable_action: str | None


@dataclass(frozen=True)
class TextReconciliationConfig:
    field_name: str
    source_key: str
    observation_documents: tuple[DocumentType, ...]
    reference_document: DocumentType
    rule_id: str
    semantics: TextSemantics


NUMERIC_RECONCILIATION_CONFIGS = (
    NumericReconciliationConfig(
        field_name="loan_amount",
        source_key="loan_amount",
        source_kind="field",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
            DocumentType.PROMISSORY_NOTE,
            DocumentType.SETTLEMENT_STATEMENT,
            DocumentType.UNDERWRITING_APPROVAL,
        ),
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        rule_id="R-001",
        curable_action="Correct the inconsistent loan amount before funding.",
    ),
    NumericReconciliationConfig(
        field_name="interest_rate",
        source_key="interest_rate",
        source_kind="field",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
            DocumentType.PROMISSORY_NOTE,
            DocumentType.UNDERWRITING_APPROVAL,
        ),
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        rule_id="R-002",
        curable_action=(
            "Request a revised Closing Disclosure reflecting the approved "
            "interest rate."
        ),
    ),
    NumericReconciliationConfig(
        field_name="term",
        source_key="term_months",
        source_kind="field",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
            DocumentType.PROMISSORY_NOTE,
            DocumentType.UNDERWRITING_APPROVAL,
        ),
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        rule_id="R-003",
        curable_action="Correct the inconsistent loan term before funding.",
    ),
    NumericReconciliationConfig(
        field_name="escrow",
        source_key="escrow",
        source_kind="field",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
            DocumentType.PROMISSORY_NOTE,
            DocumentType.SETTLEMENT_STATEMENT,
            DocumentType.UNDERWRITING_APPROVAL,
        ),
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        rule_id="R-004",
        curable_action="Review and correct the escrow setting before funding.",
    ),
    # There is no Scenario A file rule that classifies origination-fee
    # differences. We still reconcile the category so a mismatch is never
    # silently dropped; any mismatch remains unclassified and requires review.
    NumericReconciliationConfig(
        field_name="origination",
        source_key="origination",
        source_kind="fee",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
        ),
        reference_document=DocumentType.LOAN_ESTIMATE,
        rule_id=None,
        curable_action=None,
    ),
    NumericReconciliationConfig(
        field_name="title_services",
        source_key="title_services",
        source_kind="fee",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
            DocumentType.SETTLEMENT_STATEMENT,
        ),
        reference_document=DocumentType.LOAN_ESTIMATE,
        rule_id="R-005",
        curable_action=(
            "Review and correct the title-services charge before funding."
        ),
    ),
    NumericReconciliationConfig(
        field_name="cash_to_close",
        source_key="cash_to_close",
        source_kind="field",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
            DocumentType.SETTLEMENT_STATEMENT,
        ),
        reference_document=DocumentType.LOAN_ESTIMATE,
        rule_id="R-006",
        curable_action=(
            "Prepare a revised disclosure request for the cash-to-close "
            "variance."
        ),
    ),
)


TEXT_RECONCILIATION_CONFIGS = (
    TextReconciliationConfig(
        field_name="borrower_names",
        source_key="borrower_names",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
            DocumentType.PROMISSORY_NOTE,
            DocumentType.SETTLEMENT_STATEMENT,
            DocumentType.UNDERWRITING_APPROVAL,
        ),
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        rule_id="R-007",
        semantics="middle_initial_omission",
    ),
    TextReconciliationConfig(
        field_name="property_address",
        source_key="property_address",
        observation_documents=(
            DocumentType.LOAN_ESTIMATE,
            DocumentType.CLOSING_DISCLOSURE,
            DocumentType.PROMISSORY_NOTE,
            DocumentType.SETTLEMENT_STATEMENT,
            DocumentType.UNDERWRITING_APPROVAL,
        ),
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        rule_id="R-008",
        semantics="address_abbreviations",
    ),
)
