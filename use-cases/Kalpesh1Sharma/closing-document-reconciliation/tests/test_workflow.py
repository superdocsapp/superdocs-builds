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


def test_real_cached_scenario_a_reconciliation():
    documents = load_cached_documents()

    report = build_reconciliation_report(
        documents=documents,
        scenario_id="SCENARIO-A-001",
    )

    findings = {
        finding.field_name: finding
        for finding in report.findings
    }

    assert (
        findings["loan_amount"].status
        == FindingStatus.MATCH
    )

    assert (
        findings["interest_rate"].classification
        == Classification.CURABLE
    )

    assert (
        findings["term"].status
        == FindingStatus.MATCH
    )

    assert (
        findings["escrow"].status
        == FindingStatus.MATCH
    )

    assert (
        findings["title_services"].classification
        == Classification.TOLERABLE
    )

    assert (
        findings["cash_to_close"].classification
        == Classification.CURABLE
    )

    assert (
        findings["borrower_names"].status
        == FindingStatus.MATCH
    )

    assert (
        findings["property_address"].status
        == FindingStatus.MATCH
    )

    assert len(report.findings) == 8