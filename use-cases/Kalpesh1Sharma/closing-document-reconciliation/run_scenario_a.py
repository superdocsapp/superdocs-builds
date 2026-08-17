import json
from pathlib import Path

from core.models import (
    Classification,
    DocumentType,
    ExtractedMortgageDocument,
    FieldObservation,
    FileRule,
)
from core.normalize import (
    addresses_match,
    borrower_sets_match_under_middle_initial_rule,
)
from core.reconcile import (
    reconcile_numeric_field,
    reconcile_text_field,
)


CACHE_DIR = Path(
    "tests/fixtures/scenario_a_extractions"
)

GROUND_TRUTH_PATH = Path(
    "sample_documents/scenario_a/ground_truth.json"
)

OUTPUT_PATH = Path(
    "outputs/scenario_a_reconciliation.json"
)


FILES = [
    "loan_estimate",
    "closing_disclosure",
    "promissory_note",
    "settlement_statement",
    "underwriting_approval",
]


def load_documents() -> dict[
    DocumentType,
    ExtractedMortgageDocument,
]:
    documents = {}

    for stem in FILES:
        path = CACHE_DIR / f"{stem}.json"

        if not path.exists():
            raise FileNotFoundError(
                f"Missing cached extraction: {path}"
            )

        artifact = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        document = (
            ExtractedMortgageDocument.model_validate(
                artifact["canonical"]
            )
        )

        documents[document.document_type] = document

    return documents


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


def observation(
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


def optional_observation(
    documents,
    document_type,
    field_name,
):
    document = documents.get(document_type)

    if document is None:
        return None

    field = getattr(
        document,
        field_name,
    )

    return observation(
        document,
        field,
    )


def fee_observation(
    documents,
    document_type,
    fee_name,
):
    document = documents.get(document_type)

    if document is None:
        return None

    field = document.fees.get(
        fee_name
    )

    if field is None:
        return None

    return observation(
        document,
        field,
    )


def without_none(items):
    return [
        item
        for item in items
        if item is not None
    ]


def main():
    documents = load_documents()

    print(
        "Loaded cached SuperDocs extractions:"
    )

    for doc_type, document in documents.items():
        print(
            f"  ✓ {doc_type.value}: "
            f"{document.filename}"
        )

    print()

    # ---------------------------------------------------------
    # FILE RULES
    # ---------------------------------------------------------

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

    print("File-derived rules:")

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
        print(
            f"  {'✓' if rule else '✗'} "
            f"{rule_id}"
        )

    print()

    findings = []

    # =========================================================
    # 1. LOAN AMOUNT
    # =========================================================

    loan_amount_observations = without_none([
        optional_observation(
            documents,
            DocumentType.LOAN_ESTIMATE,
            "loan_amount",
        ),
        optional_observation(
            documents,
            DocumentType.CLOSING_DISCLOSURE,
            "loan_amount",
        ),
        optional_observation(
            documents,
            DocumentType.PROMISSORY_NOTE,
            "loan_amount",
        ),
        optional_observation(
            documents,
            DocumentType.SETTLEMENT_STATEMENT,
            "loan_amount",
        ),
        optional_observation(
            documents,
            DocumentType.UNDERWRITING_APPROVAL,
            "loan_amount",
        ),
    ])

    findings.append(
        reconcile_numeric_field(
            field_name="loan_amount",
            observations=loan_amount_observations,
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

    # =========================================================
    # 2. INTEREST RATE
    # =========================================================

    rate_observations = without_none([
        optional_observation(
            documents,
            DocumentType.LOAN_ESTIMATE,
            "interest_rate",
        ),
        optional_observation(
            documents,
            DocumentType.CLOSING_DISCLOSURE,
            "interest_rate",
        ),
        optional_observation(
            documents,
            DocumentType.PROMISSORY_NOTE,
            "interest_rate",
        ),
        optional_observation(
            documents,
            DocumentType.UNDERWRITING_APPROVAL,
            "interest_rate",
        ),
    ])

    findings.append(
        reconcile_numeric_field(
            field_name="interest_rate",
            observations=rate_observations,
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

    # =========================================================
    # 3. TERM
    # =========================================================

    term_observations = without_none([
        optional_observation(
            documents,
            DocumentType.LOAN_ESTIMATE,
            "term_months",
        ),
        optional_observation(
            documents,
            DocumentType.CLOSING_DISCLOSURE,
            "term_months",
        ),
        optional_observation(
            documents,
            DocumentType.PROMISSORY_NOTE,
            "term_months",
        ),
        optional_observation(
            documents,
            DocumentType.UNDERWRITING_APPROVAL,
            "term_months",
        ),
    ])

    findings.append(
        reconcile_numeric_field(
            field_name="term",
            observations=term_observations,
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

    # =========================================================
    # 4. ESCROW
    #
    # bool is deterministic in our canonical model.
    # Convert True/False to 1/0 only for comparison.
    # =========================================================

    escrow_observations = without_none([
        optional_observation(
            documents,
            DocumentType.LOAN_ESTIMATE,
            "escrow",
        ),
        optional_observation(
            documents,
            DocumentType.CLOSING_DISCLOSURE,
            "escrow",
        ),
        optional_observation(
            documents,
            DocumentType.PROMISSORY_NOTE,
            "escrow",
        ),
        optional_observation(
            documents,
            DocumentType.SETTLEMENT_STATEMENT,
            "escrow",
        ),
        optional_observation(
            documents,
            DocumentType.UNDERWRITING_APPROVAL,
            "escrow",
        ),
    ])

    findings.append(
        reconcile_numeric_field(
            field_name="escrow",
            observations=escrow_observations,
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

    # =========================================================
    # 5. TITLE SERVICES FEES
    # =========================================================

    title_observations = without_none([
        fee_observation(
            documents,
            DocumentType.LOAN_ESTIMATE,
            "title_services",
        ),
        fee_observation(
            documents,
            DocumentType.CLOSING_DISCLOSURE,
            "title_services",
        ),
        fee_observation(
            documents,
            DocumentType.SETTLEMENT_STATEMENT,
            "title_services",
        ),
    ])

    findings.append(
        reconcile_numeric_field(
            field_name="title_services",
            observations=title_observations,
            reference_document=(
                DocumentType.LOAN_ESTIMATE
            ),
            tolerance=250,
            applicable_rule=r005,
            curable_action=(
                "Review and correct the title-services "
                "charge before funding."
            ),
        )
    )

    # =========================================================
    # 6. CASH TO CLOSE
    # =========================================================

    cash_observations = without_none([
        optional_observation(
            documents,
            DocumentType.LOAN_ESTIMATE,
            "cash_to_close",
        ),
        optional_observation(
            documents,
            DocumentType.CLOSING_DISCLOSURE,
            "cash_to_close",
        ),
        optional_observation(
            documents,
            DocumentType.SETTLEMENT_STATEMENT,
            "cash_to_close",
        ),
    ])

    findings.append(
        reconcile_numeric_field(
            field_name="cash_to_close",
            observations=cash_observations,
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

    # =========================================================
    # 7. BORROWER NAMES
    # =========================================================

    borrower_observations = without_none([
        optional_observation(
            documents,
            DocumentType.LOAN_ESTIMATE,
            "borrower_names",
        ),
        optional_observation(
            documents,
            DocumentType.CLOSING_DISCLOSURE,
            "borrower_names",
        ),
        optional_observation(
            documents,
            DocumentType.PROMISSORY_NOTE,
            "borrower_names",
        ),
        optional_observation(
            documents,
            DocumentType.SETTLEMENT_STATEMENT,
            "borrower_names",
        ),
        optional_observation(
            documents,
            DocumentType.UNDERWRITING_APPROVAL,
            "borrower_names",
        ),
    ])

    findings.append(
        reconcile_text_field(
            field_name="borrower_names",
            observations=borrower_observations,
            reference_document=(
                DocumentType.UNDERWRITING_APPROVAL
            ),
            comparator=(
                borrower_sets_match_under_middle_initial_rule
            ),
            applicable_rule=r007,
        )
    )

    # =========================================================
    # 8. PROPERTY ADDRESS
    # =========================================================

    address_observations = without_none([
        optional_observation(
            documents,
            DocumentType.LOAN_ESTIMATE,
            "property_address",
        ),
        optional_observation(
            documents,
            DocumentType.CLOSING_DISCLOSURE,
            "property_address",
        ),
        optional_observation(
            documents,
            DocumentType.PROMISSORY_NOTE,
            "property_address",
        ),
        optional_observation(
            documents,
            DocumentType.SETTLEMENT_STATEMENT,
            "property_address",
        ),
        optional_observation(
            documents,
            DocumentType.UNDERWRITING_APPROVAL,
            "property_address",
        ),
    ])

    findings.append(
        reconcile_text_field(
            field_name="property_address",
            observations=address_observations,
            reference_document=(
                DocumentType.UNDERWRITING_APPROVAL
            ),
            comparator=addresses_match,
            applicable_rule=r008,
        )
    )

    # =========================================================
    # PRINT RESULTS
    # =========================================================

    print("=" * 70)
    print("RECONCILIATION RESULTS")
    print("=" * 70)

    for finding in findings:
        print()

        print(
            f"{finding.field_name.upper()}"
        )

        print(
            f"  status: "
            f"{finding.status.value}"
        )

        print(
            f"  classification: "
            f"{finding.classification.value}"
        )

        print(
            f"  human review: "
            f"{finding.requires_human_review}"
        )

        print(
            f"  explanation: "
            f"{finding.explanation}"
        )

        if finding.recommended_action:
            print(
                f"  action: "
                f"{finding.recommended_action}"
            )

    # =========================================================
    # SAVE REPORT
    # =========================================================

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_data = {
        "scenario_id": "SCENARIO-A-001",
        "findings": [
            finding.model_dump(
                mode="json"
            )
            for finding in findings
        ],
    }

    OUTPUT_PATH.write_text(
        json.dumps(
            report_data,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 70)

    print(
        f"Saved reconciliation to:"
    )

    print(
        OUTPUT_PATH.resolve()
    )

    # =========================================================
    # GROUND TRUTH CHECK
    # =========================================================

    ground_truth = json.loads(
        GROUND_TRUTH_PATH.read_text(
            encoding="utf-8"
        )
    )

    expected = ground_truth[
        "expected_results"
    ]

    findings_by_name = {
        finding.field_name: finding
        for finding in findings
    }

    print()
    print("=" * 70)
    print("GROUND TRUTH CHECK")
    print("=" * 70)

    checks = [
        (
            "loan_amount",
            findings_by_name[
                "loan_amount"
            ].status.value == "match",
        ),
        (
            "interest_rate",
            findings_by_name[
                "interest_rate"
            ].classification
            == Classification.CURABLE,
        ),
        (
            "term",
            findings_by_name[
                "term"
            ].status.value == "match",
        ),
        (
            "escrow",
            findings_by_name[
                "escrow"
            ].status.value == "match",
        ),
        (
            "title_services",
            findings_by_name[
                "title_services"
            ].classification
            == Classification.TOLERABLE,
        ),
        (
            "cash_to_close",
            findings_by_name[
                "cash_to_close"
            ].classification
            == Classification.CURABLE,
        ),
        (
            "borrower_names",
            findings_by_name[
                "borrower_names"
            ].status.value == "match",
        ),
        (
            "property_address",
            findings_by_name[
                "property_address"
            ].status.value == "match",
        ),
    ]

    passed = 0

    for name, result in checks:
        symbol = "PASS" if result else "FAIL"

        print(
            f"{symbol:4}  {name}"
        )

        if result:
            passed += 1

    print()
    print(
        f"Ground truth score: "
        f"{passed}/{len(checks)}"
    )

    if passed == len(checks):
        print(
            "Scenario A matches all seeded expectations."
        )
    else:
        print(
            "One or more seeded expectations were not reproduced."
        )


if __name__ == "__main__":
    main()