from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    LOAN_ESTIMATE = "loan_estimate"
    CLOSING_DISCLOSURE = "closing_disclosure"
    PROMISSORY_NOTE = "promissory_note"
    SETTLEMENT_STATEMENT = "settlement_statement"
    UNDERWRITING_APPROVAL = "underwriting_approval"
    UNKNOWN = "unknown"


class FindingStatus(str, Enum):
    MATCH = "match"
    VARIANCE = "variance"
    NOT_FOUND = "not_found"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Classification(str, Enum):
    TOLERABLE = "tolerable"
    CURABLE = "curable"
    UNCLASSIFIED = "unclassified"
    NOT_APPLICABLE = "not_applicable"


class FieldEvidence(BaseModel):
    """
    One extracted field together with the evidence supporting it.

    `value` is the normalized value used by Python.
    `raw_value` is exactly how the document expressed it.
    """

    value: Any | None = None
    raw_value: str | None = None
    supporting_quote: str | None = None
    source_document: str

    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )


class FileRule(BaseModel):
    """
    A rule explicitly found inside the supplied loan file.

    We do not invent mortgage/compliance rules.
    """

    rule_id: str
    rule_text: str

    source_document: str
    supporting_quote: str


class ExtractedMortgageDocument(BaseModel):
    """
    Canonical representation of any one mortgage document.

    Different source labels should all end up here.
    """

    document_type: DocumentType
    filename: str

    borrower_names: FieldEvidence
    property_address: FieldEvidence

    loan_amount: FieldEvidence
    interest_rate: FieldEvidence
    term_months: FieldEvidence
    escrow: FieldEvidence

    fees: dict[str, FieldEvidence] = Field(
        default_factory=dict
    )

    cash_to_close: FieldEvidence

    rules: list[FileRule] = Field(
        default_factory=list
    )

    extraction_notes: list[str] = Field(
        default_factory=list
    )


class FieldObservation(BaseModel):
    """
    A canonical value observed in one particular document.
    """

    document_type: DocumentType
    filename: str

    value: Any | None
    raw_value: str | None = None
    supporting_quote: str | None = None


class ReconciliationFinding(BaseModel):
    """
    Result of comparing one field across the loan file.
    """

    field_name: str

    status: FindingStatus
    classification: Classification = Classification.NOT_APPLICABLE

    observations: list[FieldObservation]

    applicable_rule: FileRule | None = None

    explanation: str

    recommended_action: str | None = None

    requires_human_review: bool = False


class ReconciliationReport(BaseModel):
    scenario_id: str

    findings: list[ReconciliationFinding]

    warnings: list[str] = Field(
        default_factory=list
    )