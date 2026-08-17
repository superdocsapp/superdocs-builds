from __future__ import annotations

from core.models import (
    DocumentType,
    ExtractedMortgageDocument,
    FieldObservation,
    FileRule,
    ReconciliationReport,
)
from core.normalize import (
    addresses_match,
    borrower_sets_match_under_middle_initial_rule,
)
from core.reconcile import (
    reconcile_numeric_field,
    reconcile_text_field,
)


def find_rule(
    documents: dict[
        DocumentType,
        ExtractedMortgageDocument,
    ],
    rule_id: str,
) -> FileRule | None:
    for document in documents.values():
        for rule in document.rules:
            if rule.rule_id == rule_id:
                return rule

    return None


def _observation(
    document: ExtractedMortgageDocument,
    field,
) -> FieldObservation:
    return FieldObservation(
        document_type=document.document_type,
        filename=document.filename,
        value=field.value,
        raw_value=field.raw_value,
        supporting_quote=field.supporting_quote,
    )


def _field_observation(
    documents: dict[
        DocumentType,
        ExtractedMortgageDocument,
    ],
    document_type: DocumentType,
    field_name: str,
) -> FieldObservation | None:
    document = documents.get(document_type)

    if document is None:
        return None

    field = getattr(
        document,
        field_name,
    )

    return _observation(
        document,
        field,
    )


def _fee_observation(
    documents: dict[
        DocumentType,
        ExtractedMortgageDocument,
    ],
    document_type: DocumentType,
    fee_name: str,
) -> FieldObservation | None:
    document = documents.get(document_type)

    if document is None:
        return None

    field = document.fees.get(
        fee_name
    )

    if field is None:
        return None

    return _observation(
        document,
        field,
    )


def _without_none(
    items: list[
        FieldObservation | None
    ],
) -> list[FieldObservation]:
    return [
        item
        for item in items
        if item is not None
    ]


def build_reconciliation_report(
    *,
    documents: dict[
        DocumentType,
        ExtractedMortgageDocument,
    ],
    scenario_id: str,
) -> ReconciliationReport:
    """
    Reconcile a mortgage closing file using only:

    - values supported by the extracted documents
    - file-specific rules extracted from the file

    No external mortgage-law rules are applied here.
    """

    required_types = {
        DocumentType.LOAN_ESTIMATE,
        DocumentType.CLOSING_DISCLOSURE,
        DocumentType.PROMISSORY_NOTE,
        DocumentType.SETTLEMENT_STATEMENT,
        DocumentType.UNDERWRITING_APPROVAL,
    }

    missing_types = (
        required_types
        - set(documents.keys())
    )

    warnings: list[str] = []

    if missing_types:
        warnings.append(
            "Missing expected document type(s): "
            + ", ".join(
                sorted(
                    item.value
                    for item in missing_types
                )
            )
        )

    r001 = find_rule(
        documents,
        "R-001",
    )
    r002 = find_rule(
        documents,
        "R-002",
    )
    r003 = find_rule(
        documents,
        "R-003",
    )
    r004 = find_rule(
        documents,
        "R-004",
    )
    r005 = find_rule(
        documents,
        "R-005",
    )
    r006 = find_rule(
        documents,
        "R-006",
    )
    r007 = find_rule(
        documents,
        "R-007",
    )
    r008 = find_rule(
        documents,
        "R-008",
    )

    for rule_id, rule in [
        ("R-001", r001),
        ("R-002", r002),
        ("R-003", r003),
        ("R-004", r004),
        ("R-005", r005),
        ("R-006", r006),
        ("R-007", r007),
        ("R-008", r008),
    ]:
        if rule is None:
            warnings.append(
                f"{rule_id} was not found in the file."
            )

    findings = []

    # ---------------------------------------------------------
    # Loan amount
    # ---------------------------------------------------------

    findings.append(
        reconcile_numeric_field(
            field_name="loan_amount",
            observations=_without_none([
                _field_observation(
                    documents,
                    DocumentType.LOAN_ESTIMATE,
                    "loan_amount",
                ),
                _field_observation(
                    documents,
                    DocumentType.CLOSING_DISCLOSURE,
                    "loan_amount",
                ),
                _field_observation(
                    documents,
                    DocumentType.PROMISSORY_NOTE,
                    "loan_amount",
                ),
                _field_observation(
                    documents,
                    DocumentType.SETTLEMENT_STATEMENT,
                    "loan_amount",
                ),
                _field_observation(
                    documents,
                    DocumentType.UNDERWRITING_APPROVAL,
                    "loan_amount",
                ),
            ]),
            reference_document=(
                DocumentType.UNDERWRITING_APPROVAL
            ),
            tolerance=0,
            applicable_rule=r001,
            curable_action=(
                "Correct the inconsistent loan amount "
                "before funding."
            ),
        )
    )

    # ---------------------------------------------------------
    # Interest rate
    # ---------------------------------------------------------

    findings.append(
        reconcile_numeric_field(
            field_name="interest_rate",
            observations=_without_none([
                _field_observation(
                    documents,
                    DocumentType.LOAN_ESTIMATE,
                    "interest_rate",
                ),
                _field_observation(
                    documents,
                    DocumentType.CLOSING_DISCLOSURE,
                    "interest_rate",
                ),
                _field_observation(
                    documents,
                    DocumentType.PROMISSORY_NOTE,
                    "interest_rate",
                ),
                _field_observation(
                    documents,
                    DocumentType.UNDERWRITING_APPROVAL,
                    "interest_rate",
                ),
            ]),
            reference_document=(
                DocumentType.UNDERWRITING_APPROVAL
            ),
            tolerance=0,
            applicable_rule=r002,
            curable_action=(
                "Request a revised Closing Disclosure "
                "reflecting the approved interest rate."
            ),
        )
    )

    # ---------------------------------------------------------
    # Term
    # ---------------------------------------------------------

    findings.append(
        reconcile_numeric_field(
            field_name="term",
            observations=_without_none([
                _field_observation(
                    documents,
                    DocumentType.LOAN_ESTIMATE,
                    "term_months",
                ),
                _field_observation(
                    documents,
                    DocumentType.CLOSING_DISCLOSURE,
                    "term_months",
                ),
                _field_observation(
                    documents,
                    DocumentType.PROMISSORY_NOTE,
                    "term_months",
                ),
                _field_observation(
                    documents,
                    DocumentType.UNDERWRITING_APPROVAL,
                    "term_months",
                ),
            ]),
            reference_document=(
                DocumentType.UNDERWRITING_APPROVAL
            ),
            tolerance=0,
            applicable_rule=r003,
            curable_action=(
                "Correct the inconsistent loan term "
                "before funding."
            ),
        )
    )

    # ---------------------------------------------------------
    # Escrow
    # ---------------------------------------------------------

    findings.append(
        reconcile_numeric_field(
            field_name="escrow",
            observations=_without_none([
                _field_observation(
                    documents,
                    DocumentType.LOAN_ESTIMATE,
                    "escrow",
                ),
                _field_observation(
                    documents,
                    DocumentType.CLOSING_DISCLOSURE,
                    "escrow",
                ),
                _field_observation(
                    documents,
                    DocumentType.PROMISSORY_NOTE,
                    "escrow",
                ),
                _field_observation(
                    documents,
                    DocumentType.SETTLEMENT_STATEMENT,
                    "escrow",
                ),
                _field_observation(
                    documents,
                    DocumentType.UNDERWRITING_APPROVAL,
                    "escrow",
                ),
            ]),
            reference_document=(
                DocumentType.UNDERWRITING_APPROVAL
            ),
            tolerance=0,
            applicable_rule=r004,
            curable_action=(
                "Review and correct the escrow setting "
                "before funding."
            ),
        )
    )

    # ---------------------------------------------------------
    # Title / settlement services
    # ---------------------------------------------------------

    findings.append(
        reconcile_numeric_field(
            field_name="title_services",
            observations=_without_none([
                _fee_observation(
                    documents,
                    DocumentType.LOAN_ESTIMATE,
                    "title_services",
                ),
                _fee_observation(
                    documents,
                    DocumentType.CLOSING_DISCLOSURE,
                    "title_services",
                ),
                _fee_observation(
                    documents,
                    DocumentType.SETTLEMENT_STATEMENT,
                    "title_services",
                ),
            ]),
            reference_document=(
                DocumentType.LOAN_ESTIMATE
            ),
            tolerance=250,
            applicable_rule=r005,
            curable_action=(
                "Review and correct the "
                "title-services charge before funding."
            ),
        )
    )

    # ---------------------------------------------------------
    # Cash to close
    # ---------------------------------------------------------

    findings.append(
        reconcile_numeric_field(
            field_name="cash_to_close",
            observations=_without_none([
                _field_observation(
                    documents,
                    DocumentType.LOAN_ESTIMATE,
                    "cash_to_close",
                ),
                _field_observation(
                    documents,
                    DocumentType.CLOSING_DISCLOSURE,
                    "cash_to_close",
                ),
                _field_observation(
                    documents,
                    DocumentType.SETTLEMENT_STATEMENT,
                    "cash_to_close",
                ),
            ]),
            reference_document=(
                DocumentType.LOAN_ESTIMATE
            ),
            tolerance=500,
            applicable_rule=r006,
            curable_action=(
                "Prepare a revised disclosure request "
                "for the cash-to-close variance."
            ),
        )
    )

    # ---------------------------------------------------------
    # Borrower names
    # ---------------------------------------------------------

    findings.append(
        reconcile_text_field(
            field_name="borrower_names",
            observations=_without_none([
                _field_observation(
                    documents,
                    DocumentType.LOAN_ESTIMATE,
                    "borrower_names",
                ),
                _field_observation(
                    documents,
                    DocumentType.CLOSING_DISCLOSURE,
                    "borrower_names",
                ),
                _field_observation(
                    documents,
                    DocumentType.PROMISSORY_NOTE,
                    "borrower_names",
                ),
                _field_observation(
                    documents,
                    DocumentType.SETTLEMENT_STATEMENT,
                    "borrower_names",
                ),
                _field_observation(
                    documents,
                    DocumentType.UNDERWRITING_APPROVAL,
                    "borrower_names",
                ),
            ]),
            reference_document=(
                DocumentType.UNDERWRITING_APPROVAL
            ),
            comparator=(
                borrower_sets_match_under_middle_initial_rule
            ),
            applicable_rule=r007,
        )
    )

    # ---------------------------------------------------------
    # Property address
    # ---------------------------------------------------------

    findings.append(
        reconcile_text_field(
            field_name="property_address",
            observations=_without_none([
                _field_observation(
                    documents,
                    DocumentType.LOAN_ESTIMATE,
                    "property_address",
                ),
                _field_observation(
                    documents,
                    DocumentType.CLOSING_DISCLOSURE,
                    "property_address",
                ),
                _field_observation(
                    documents,
                    DocumentType.PROMISSORY_NOTE,
                    "property_address",
                ),
                _field_observation(
                    documents,
                    DocumentType.SETTLEMENT_STATEMENT,
                    "property_address",
                ),
                _field_observation(
                    documents,
                    DocumentType.UNDERWRITING_APPROVAL,
                    "property_address",
                ),
            ]),
            reference_document=(
                DocumentType.UNDERWRITING_APPROVAL
            ),
            comparator=addresses_match,
            applicable_rule=r008,
        )
    )

    return ReconciliationReport(
        scenario_id=scenario_id,
        findings=findings,
        warnings=warnings,
    )