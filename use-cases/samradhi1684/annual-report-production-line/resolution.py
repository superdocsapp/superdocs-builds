import os
import json
import requests
from pathlib import Path


API_KEY = os.environ["SUPERDOCS_API_KEY"]

BASE_URL = "https://api.superdocs.app"
SESSION_ID = "annual-report-2026"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

REPORT_STATE = Path("report_state.json")
CONSISTENCY_REPORT = Path("number-consistency-report.json")
RESOLUTION_REPORT = Path("resolution-report.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


def build_resolution_prompt(state, consistency_report):
    findings = consistency_report.get("findings", [])

    mismatches = [
        finding
        for finding in findings
        if finding.get("status") == "MISMATCH"
    ]

    # Only unresolved inconsistencies need resolution.
    if not mismatches:
        return None

    sections = state.get("sections", {})

    workflow_context = {}

    for section_name, section_state in sections.items():
        workflow_context[section_name] = {
            "stage": section_state.get("stage"),
            "document_id": section_state.get("document_id"),
        }

    prompt = f"""
You are assisting with the resolution of cross-document
inconsistencies in an annual report.

The report is:

{state.get("report_name", "Annual Report")}

The report contains multiple documents that move through
different review stages.

Workflow state:

{json.dumps(workflow_context, indent=2)}

The following inconsistencies were detected:

{json.dumps(mismatches, indent=2)}

Your task is to determine how each inconsistency should be
resolved.

For each mismatch:

1. Identify the underlying concept.
2. Determine which document appears to be the authoritative
   source for this fact.
3. Consider the document's current review stage when making
   this determination.
4. Identify which document should be reviewed or corrected.
5. State the current value in that document.
6. State the proposed value.
7. Explain the reasoning.
8. Do NOT modify any documents.
9. Do NOT assume that a particular document type is always
   authoritative. Use the provided evidence and workflow state.

Return ONLY valid JSON.

Use exactly this structure:

{{
  "resolutions": [
    {{
      "concept": "...",
      "status": "ACTION_REQUIRED",
      "authoritative_document": "...",
      "document_to_review": "...",
      "current_value": "...",
      "proposed_value": "...",
      "reason": "..."
    }}
  ]
}}
"""

    return prompt


def call_superdocs(prompt):
    payload = {
        "message": prompt,
        "session_id": SESSION_ID,
        "approval_mode": "approve_all",
    }

    print("\nRunning SuperDocs resolution analysis...")

    response = requests.post(
        f"{BASE_URL}/v1/chat",
        headers=HEADERS,
        json=payload,
        timeout=300,
    )

    print("Status:", response.status_code)

    response.raise_for_status()

    result = response.json()

    return result.get("response", "")


def parse_json_response(response_text):
    """
    Extract JSON even if SuperDocs wraps it in markdown.
    """

    cleaned = response_text.strip()

    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1]
        cleaned = cleaned.split("```", 1)[0].strip()

    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1]
        cleaned = cleaned.split("```", 1)[0].strip()

    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]

    try:
        return json.loads(cleaned)

    except json.JSONDecodeError as exc:
        print("\nCould not parse structured resolution report.")
        print("Parser error:", exc)

        print("\nRaw SuperDocs response:")
        print(response_text)

        return None


def print_resolution_report(report):
    resolutions = report.get("resolutions", [])

    print("\n" + "=" * 70)
    print("CROSS-DOCUMENT RESOLUTION REPORT")
    print("=" * 70)

    if not resolutions:
        print("\nNo resolution actions required.")
        return

    for resolution in resolutions:

        print("\n" + "-" * 70)

        print(
            f"Concept: "
            f"{resolution.get('concept', 'Unknown')}"
        )

        print(
            f"Status:  "
            f"{resolution.get('status', 'UNKNOWN')}"
        )

        print(
            f"\nAuthoritative document:\n"
            f"  {resolution.get('authoritative_document', 'Unknown')}"
        )

        print(
            f"\nDocument to review:\n"
            f"  {resolution.get('document_to_review', 'Unknown')}"
        )

        print(
            f"\nCurrent value:\n"
            f"  {resolution.get('current_value', 'Unknown')}"
        )

        print(
            f"\nProposed value:\n"
            f"  {resolution.get('proposed_value', 'Unknown')}"
        )

        print(
            f"\nReason:\n"
            f"  {resolution.get('reason', 'No reason provided')}"
        )

    print("\n" + "=" * 70)


def main():

    print("\n" + "=" * 70)
    print("ANNUAL REPORT CONSISTENCY RESOLUTION")
    print("=" * 70)

    if not REPORT_STATE.exists():
        print("\nMissing report_state.json")
        return

    if not CONSISTENCY_REPORT.exists():
        print("\nMissing number-consistency-report.json")
        print("Run audit.py first.")
        return

    state = load_json(REPORT_STATE)
    consistency_report = load_json(CONSISTENCY_REPORT)

    prompt = build_resolution_prompt(
        state,
        consistency_report,
    )

    if prompt is None:
        print("\nNo mismatches found.")
        print("No resolution required.")
        return

    response_text = call_superdocs(prompt)

    report = parse_json_response(response_text)

    if report is None:
        return

    save_json(
        RESOLUTION_REPORT,
        report,
    )

    print(
        f"\nSaved: {RESOLUTION_REPORT}"
    )

    print_resolution_report(report)


if __name__ == "__main__":
    main()