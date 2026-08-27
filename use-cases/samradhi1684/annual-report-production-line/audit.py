import json
from pathlib import Path

from consistency_check import load_documents, main as run_consistency_check


REPORT_STATE = Path("report_state.json")
CONSISTENCY_REPORT = Path("number-consistency-report.json")


def load_state():
    with open(REPORT_STATE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_consistency_report():
    if not CONSISTENCY_REPORT.exists():
        return None

    with open(CONSISTENCY_REPORT, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print("\n" + "=" * 70)
    print("ANNUAL REPORT CROSS-DOCUMENT AUDIT")
    print("=" * 70)

    state = load_state()

    report_name = state.get(
        "report_name",
        state.get("report_title", "Annual Report")
    )

    print(f"\nReport: {report_name}")

    print("\nRunning number-consistency audit...")

    run_consistency_check()

    report = load_consistency_report()

    
    if not report:
        print("\nNo structured consistency report was generated.")
        return

    if report.get("status") in {"parse_failed", "invalid_structure"}:
        print("\n⚠️ Consistency audit could not be completed.")
        print("SuperDocs did not return a valid structured report.")
        print("\nRaw response:")
        print(report.get("raw_response", "No response available."))

        state["overall_status"] = "audit_failed"
        state["consistency_audit"] = {
            "status": "audit_failed",
            "total_findings": 0,
            "matches": 0,
            "mismatches": 0,
            "affected_documents": [],
            "report_file": "number-consistency-report.json",
        }

        with open(REPORT_STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        print("\nReport state updated.")
        print("\nOverall report status: audit_failed")
        print("\n" + "=" * 70)

        return

    findings = report.get("findings", [])

    matches = [
        finding
        for finding in findings
        if finding.get("status") == "MATCH"
    ]

    mismatches = [
        finding
        for finding in findings
        if finding.get("status") == "MISMATCH"
    ]

    affected_documents = set()

    for finding in mismatches:
        affected_documents.add(finding["left_document"])
        affected_documents.add(finding["right_document"])

    print("\nAffected documents:")

    for document in sorted(affected_documents):
        print(f"  ⚠️ {document}")


    if mismatches:
        overall_status = "review_required"
    else:
        overall_status = "consistent"


    state["overall_status"] = overall_status
    state["consistency_audit"] = {
        "status": overall_status,
        "total_findings": len(findings),
        "matches": len(matches),
        "mismatches": len(mismatches),
        "affected_documents": sorted(affected_documents),
        "report_file": "number-consistency-report.json",
    }

    with open(REPORT_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print("\nReport state updated.")

    print(f"\nOverall report status: {overall_status}")


    print("\n" + "-" * 70)
    print("AUDIT SUMMARY")
    print("-" * 70)

    print(f"Total findings: {len(findings)}")
    print(f"Matches:        {len(matches)}")
    print(f"Mismatches:     {len(mismatches)}")

    if mismatches:
        print("\n⚠️ CROSS-DOCUMENT INCONSISTENCIES FOUND")

        for finding in mismatches:
            print(
                f"\n{finding['concept']}"
            )

            print(
                f"  {finding['left_document']}: "
                f"{finding['left_value']}"
            )

            print(
                f"  {finding['right_document']}: "
                f"{finding['right_value']}"
            )

            print(
                f"  {finding['explanation']}"
            )

        print("\nReport requires review.")

    else:
        print("\n✅ No cross-document inconsistencies found.")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()