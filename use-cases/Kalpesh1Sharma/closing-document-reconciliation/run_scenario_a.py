import json
from pathlib import Path

from core.models import (
    Classification,
    DocumentType,
    ExtractedMortgageDocument,
    FindingStatus,
)
from core.workflow import build_reconciliation_report


CACHE_DIR = Path(
    "tests/fixtures/scenario_a_extractions"
)
GROUND_TRUTH_PATH = Path(
    "sample_documents/scenario_a/ground_truth.json"
)
OUTPUT_PATH = Path(
    "outputs/scenario_a_reconciliation.json"
)

STEMS = [
    "loan_estimate",
    "closing_disclosure",
    "promissory_note",
    "settlement_statement",
    "underwriting_approval",
]


def load_documents():
    documents = {}

    for stem in STEMS:
        artifact = json.loads(
            (CACHE_DIR / f"{stem}.json").read_text(
                encoding="utf-8"
            )
        )

        document = ExtractedMortgageDocument.model_validate(
            artifact["canonical"]
        )
        documents[document.document_type] = document

    return documents


def finding_passes(finding, expected_status: str) -> bool:
    if expected_status in {
        "match",
        "match_after_normalization",
    }:
        return finding.status == FindingStatus.MATCH

    if expected_status == "tolerable":
        return finding.classification == Classification.TOLERABLE

    if expected_status == "curable":
        return finding.classification == Classification.CURABLE

    if expected_status == "unclassified":
        return finding.classification == Classification.UNCLASSIFIED

    return False


def main():
    documents = load_documents()

    report = build_reconciliation_report(
        documents=documents,
        scenario_id="SCENARIO-A-001",
    )

    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUT_PATH.write_text(
        json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        ),
        encoding="utf-8",
    )

    findings = {
        finding.field_name: finding
        for finding in report.findings
    }

    ground_truth = json.loads(
        GROUND_TRUTH_PATH.read_text(
            encoding="utf-8"
        )
    )["expected_results"]

    passed = 0

    print("=" * 70)
    print("SCENARIO A GROUND TRUTH CHECK")
    print("=" * 70)

    for field_name, expected in ground_truth.items():
        finding = findings.get(field_name)
        ok = (
            finding is not None
            and finding_passes(
                finding,
                expected["status"],
            )
        )

        passed += int(ok)
        print(
            f"{'PASS' if ok else 'FAIL'}  {field_name}"
        )

    print()
    print(
        f"{passed}/{len(ground_truth)} ground-truth findings passed."
    )
    print(
        f"Saved reconciliation to: {OUTPUT_PATH.resolve()}"
    )

    if passed != len(ground_truth):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
