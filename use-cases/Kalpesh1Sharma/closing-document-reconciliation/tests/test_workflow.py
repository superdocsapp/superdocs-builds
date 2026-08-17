import json
from pathlib import Path

from core.models import (
    Classification,
    DocumentType,
    ExtractedMortgageDocument,
    FindingStatus,
)
from core.workflow import (
    build_reconciliation_report,
)


CACHE_DIR = Path(
    "tests/fixtures/scenario_a_extractions"
)

STEMS = [
    "loan_estimate",
    "closing_disclosure",
    "promissory_note",
    "settlement_statement",
    "underwriting_approval",
]


def load_cached_documents():
    documents = {}

    for stem in STEMS:
        artifact = json.loads(
            (
                CACHE_DIR
                / f"{stem}.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        document = (
            ExtractedMortgageDocument.model_validate(
                artifact["canonical"]
            )
        )

        documents[
            document.document_type
        ] = document

    return documents


def findings_by_name(report):
    return {
        finding.field_name: finding
        for finding in report.findings
    }


def underwriting_rule(documents, rule_id: str):
    approval = documents[
        DocumentType.UNDERWRITING_APPROVAL
    ]

    return next(
        rule
        for rule in approval.rules
        if rule.rule_id == rule_id
    )


def test_real_cached_scenario_a_reconciliation():
    documents = load_cached_documents()

    report = build_reconciliation_report(
        documents=documents,
        scenario_id="SCENARIO-A-001",
    )

    findings = findings_by_name(report)

    assert findings["loan_amount"].status == FindingStatus.MATCH
    assert findings["interest_rate"].classification == Classification.CURABLE
    assert findings["term"].status == FindingStatus.MATCH
    assert findings["escrow"].status == FindingStatus.MATCH
    assert findings["origination"].status == FindingStatus.MATCH
    assert findings["title_services"].classification == Classification.TOLERABLE
    assert findings["cash_to_close"].classification == Classification.CURABLE
    assert findings["borrower_names"].status == FindingStatus.MATCH
    assert findings["property_address"].status == FindingStatus.MATCH

    assert len(report.findings) == 9


def test_origination_difference_is_not_silently_dropped():
    documents = load_cached_documents()

    closing = documents[
        DocumentType.CLOSING_DISCLOSURE
    ]
    closing.fees["origination"].value = 4800.0
    closing.fees["origination"].raw_value = "$4,800.00"
    closing.fees["origination"].supporting_quote = (
        "Loan Costs — Origination $4,800.00"
    )

    report = build_reconciliation_report(
        documents=documents,
        scenario_id="ORIGINATION-VARIANCE",
    )

    finding = findings_by_name(report)[
        "origination"
    ]

    assert finding.status == FindingStatus.VARIANCE
    assert finding.classification == Classification.UNCLASSIFIED
    assert finding.requires_human_review is True


def test_title_threshold_comes_from_rule_text_not_hardcoded_value():
    documents = load_cached_documents()

    r005 = underwriting_rule(
        documents,
        "R-005",
    )

    r005.rule_text = (
        "A Title & Settlement Services fee difference of up to "
        "$100.00 from the Loan Estimate is tolerable. A difference "
        "greater than $100.00 requires review and correction."
    )
    r005.supporting_quote = r005.rule_text

    report = build_reconciliation_report(
        documents=documents,
        scenario_id="RULE-100",
    )

    finding = findings_by_name(report)[
        "title_services"
    ]

    assert finding.status == FindingStatus.VARIANCE
    assert finding.classification == Classification.CURABLE
    assert "100" in finding.explanation
    assert "250" not in finding.explanation


def test_middle_initial_normalization_requires_supporting_rule_text():
    documents = load_cached_documents()

    r007 = underwriting_rule(
        documents,
        "R-007",
    )
    r007.rule_text = "Borrower names must match exactly."
    r007.supporting_quote = r007.rule_text

    report = build_reconciliation_report(
        documents=documents,
        scenario_id="STRICT-NAMES",
    )

    finding = findings_by_name(report)[
        "borrower_names"
    ]

    assert finding.status == FindingStatus.VARIANCE
    assert finding.classification == Classification.UNCLASSIFIED


def test_address_abbreviation_normalization_requires_supporting_rule_text():
    documents = load_cached_documents()

    r008 = underwriting_rule(
        documents,
        "R-008",
    )
    r008.rule_text = "The property address must match exactly."
    r008.supporting_quote = r008.rule_text

    report = build_reconciliation_report(
        documents=documents,
        scenario_id="STRICT-ADDRESS",
    )

    finding = findings_by_name(report)[
        "property_address"
    ]

    assert finding.status == FindingStatus.VARIANCE
    assert finding.classification == Classification.UNCLASSIFIED
