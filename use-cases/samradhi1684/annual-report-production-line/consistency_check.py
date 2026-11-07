import os
import requests
import json

from consistency import build_candidate_pairs


API_KEY = os.environ["SUPERDOCS_API_KEY"]

BASE_URL = "https://api.superdocs.app"
SESSION_ID = "annual-report-2026"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

REPORT_FILE = "number-consistency-report.json"


def load_documents():
    documents = {}

    document_files = {
        "Chair Statement": "documents/chair-statement.html",
        "Strategy": "documents/strategy.html",
        "Business Review": "documents/business-review.html",
        "Governance": "documents/governance.html",
        "Financial Statements": "documents/financial-statements.html",
    }

    for document_name, file_path in document_files.items():
        with open(file_path, "r", encoding="utf-8") as f:
            documents[document_name] = f.read()

    return documents


def extract_json(text):
    """
    Try to recover a JSON object from an LLM response.
    """

    text = text.strip()

    # Case 1: ```json ... ```
    if "```json" in text:
        text = text.split("```json", 1)[1]
        text = text.split("```", 1)[0].strip()

    # Case 2: ``` ... ```
    elif "```" in text:
        text = text.split("```", 1)[1]
        text = text.split("```", 1)[0].strip()

    # Case 3: raw JSON embedded in prose
    else:
        start = text.find("{")
        end = text.rfind("}")

        if start != -1 and end != -1:
            text = text[start:end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def main():

    documents = load_documents()

    pairs = build_candidate_pairs(documents)

    print(f"Generated {len(pairs)} candidate pairs.")

    prompt = f"""
You are performing a READ-ONLY number-consistency audit of an annual report.

IMPORTANT:
- This is an analysis-only request.
- DO NOT edit any document.
- DO NOT update any document.
- DO NOT replace any values.
- DO NOT perform any document action.
- DO NOT interpret this request as an instruction to modify the report.

You are given numeric candidates extracted from multiple documents.

Determine which candidates refer to the SAME underlying business fact.

Rules:

- Compare numbers only when they describe the same concept.
- Ignore years, dates, page numbers, and unrelated numbers.
- Identify matching figures as MATCH.
- Identify conflicting figures as MISMATCH.
- Do not modify any documents.
- Do not provide commentary.
- Do not provide markdown.
- Do not use code fences.
- Your ENTIRE response must be valid JSON.
- The first character of your response must be {{.
- The last character of your response must be }}.

Return EXACTLY this structure:

{{
  "findings": [
    {{
      "concept": "2025 Annual Revenue",
      "status": "MISMATCH",
      "left_document": "Business Review",
      "left_value": "£125 million",
      "right_document": "Financial Statements",
      "right_value": "£120 million",
      "explanation": "Brief explanation of the discrepancy."
    }}
  ]
}}

If there are no comparable facts, return:

{{
  "findings": []
}}

Candidates:

{json.dumps(pairs, indent=2, ensure_ascii=False)}
"""

    payload = {
        "message": prompt,
        "session_id": SESSION_ID,
        "approval_mode": "approve_all",
    }

    print("\nRunning SuperDocs consistency analysis...")

    response = requests.post(
        f"{BASE_URL}/v1/chat",
        headers=HEADERS,
        json=payload,
        timeout=300,
    )

    print("Status:", response.status_code)

    response.raise_for_status()

    result = response.json()

    response_text = result.get("response", "").strip()

    report = extract_json(response_text)

    if report is None:
        print("\nCould not parse structured consistency report.")
        print("\nRaw SuperDocs response:")
        print(response_text)

        # IMPORTANT:
        # Always create a valid report file so audit.py does not crash.
        report = {
            "findings": [],
            "status": "parse_failed",
            "raw_response": response_text,
        }

        

    else:

        # Validate the expected structure.
        if not isinstance(report, dict):
            report = {
                "findings": [],
                "status": "invalid_structure",
                "raw_response": response_text,
            }

        elif not isinstance(report.get("findings"), list):
            report["findings"] = []

    with open(
        REPORT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            report,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"\nSaved: {REPORT_FILE}")

    findings = report.get("findings", [])

    for finding in findings:

        print("\n" + "-" * 70)

        print(
            f"Concept: {finding.get('concept', 'Unknown')}"
        )

        print(
            f"Status:  {finding.get('status', 'UNKNOWN')}"
        )

        print(
            f"{finding.get('left_document', '')}: "
            f"{finding.get('left_value', '')}"
        )

        print(
            f"{finding.get('right_document', '')}: "
            f"{finding.get('right_value', '')}"
        )

        print(
            f"Explanation: "
            f"{finding.get('explanation', '')}"
        )

    print("\n" + "=" * 70)
    print("SUPERDOCS NUMBER CONSISTENCY REPORT")
    print("=" * 70)

    print(response_text)

    return report


if __name__ == "__main__":
    main()