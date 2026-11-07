import json
import os
import re
from pathlib import Path

import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.environ["SUPERDOCS_API_KEY"]

BASE_URL = "https://api.superdocs.app"

SESSION_ID = "annual-report-multidoc-test"

DOCUMENTS_DIR = Path("documents")

DOCUMENTS = {
    "Chair Statement": "chair-statement.html",
    "Strategy": "strategy.html",
    "Business Review": "business-review.html",
    "Governance": "governance.html",
    "Financial Statements": "financial-statements.html",
}

REPORT_TITLE = "Annual Report 2026"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

OUTPUT_FILE = Path("house-style-report.json")


# ============================================================
# HOUSE STYLE
# ============================================================

HOUSE_STYLE_RULES = """
You are reviewing a section of a corporate Annual Report.

Apply the following house style rules.

1. CURRENCY
   - Use the pound symbol for GBP.
   - Preferred format:
       £120 million
   - Do not use:
       £120m
       GBP 120 million
       GBP120m
   - Do not insert a space between £ and the number.

2. PERCENTAGES
   - Use the % symbol for numerical percentages.
   - Preferred:
       32%
   - Do not use:
       32 percent
       thirty-two percent

3. EMPLOYEE COUNTS
   - Use thousands separators for four-digit employee counts.
   - Preferred:
       4,500 people
   - Do not use:
       4500 people

4. DOCUMENT TITLE
   - The document's <title> and primary <h1> must match the
     supplied document name exactly.

5. HEADING STRUCTURE
   - There should be exactly one primary <h1>.
   - The document should contain one or more <h2> headings.
   - Do not unnecessarily change the existing heading hierarchy.

6. REPORT YEAR
   - Preserve references to the reporting period.
   - Do not invent or alter financial/reporting years.

7. CHARACTER ENCODING
   - Correct obvious mojibake such as:
       Â£
       â€“
       â€™
       â€œ
       â€
   - Preserve the intended character.

8. CONTENT FIDELITY
   - Do NOT change factual content.
   - Do NOT change financial figures unless the instruction explicitly
     asks you to do so.
   - Do NOT rewrite prose merely for stylistic preference.
   - Only make changes necessary to enforce the rules above.

9. HTML FIDELITY
   - Preserve the existing HTML structure wherever possible.
   - Preserve all content that does not require a style correction.
   - Do not remove sections, paragraphs, headings, or formatting
     unrelated to a style violation.
"""


# ============================================================
# HELPERS
# ============================================================

def load_document(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(
            f"Document not found: {path}"
        )

    return path.read_text(encoding="utf-8")


def save_document(path: Path, html: str) -> None:
    path.write_text(
        html,
        encoding="utf-8",
    )


def extract_updated_html(response_json):
    """
    Extract the final HTML returned by SuperDocs.

    The synchronous /v1/chat response contains the document changes
    object when the edit is completed.
    """

    document_changes = response_json.get(
        "document_changes"
    )

    if not document_changes:
        return None

    return document_changes.get(
        "updated_html"
    )


# ============================================================
# SUPDOCS HOUSE-STYLE REVIEW
# ============================================================

def review_with_superdocs(
    document_name: str,
    html: str,
):
    """
    Ask SuperDocs to review one annual-report section
    against the house style.
    """

    message = f"""
Review the following document against the annual-report house style.

DOCUMENT:
{document_name}

{HOUSE_STYLE_RULES}

Important:

- This is a STYLE REVIEW.
- Do not change factual content.
- Do not change financial values.
- Do not invent missing information.
- If the document already complies, make no changes.
- If changes are required, propose only the minimum necessary edits.

Return the corrected document through the normal SuperDocs
document-edit workflow.

DOCUMENT HTML:
{html}
"""

    payload = {
        "session_id": SESSION_ID,
        "document_html": html,
        "message": message,
        "approval_mode": "ask_every_time",
    }

    print(
        f"\nSending {document_name} to SuperDocs..."
    )

    response = requests.post(
        f"{BASE_URL}/v1/chat",
        headers=HEADERS,
        json=payload,
        timeout=300,
    )

    print(
        "Status:",
        response.status_code,
    )

    if not response.ok:
        print(response.text)
        response.raise_for_status()

    return response.json()


# ============================================================
# APPROVAL
# ============================================================

def print_proposed_changes(response_json):
    """
    Display proposed changes returned by SuperDocs.

    The exact structure can vary depending on the response,
    so this function intentionally prints the useful fields
    without assuming every response contains a change.
    """

    print("\n" + "-" * 70)
    print("SUPERDOCS HOUSE-STYLE RESPONSE")
    print("-" * 70)

    print(
        json.dumps(
            response_json,
            indent=2,
            ensure_ascii=False,
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 70)
    print("ANNUAL REPORT HOUSE STYLE — SUPERDOCS")
    print("=" * 70)

    print(
        f"\nReport: {REPORT_TITLE}"
    )

    print(
        f"Session: {SESSION_ID}"
    )

    results = []

    for document_name, filename in DOCUMENTS.items():

        path = DOCUMENTS_DIR / filename

        print("\n" + "=" * 70)
        print(document_name)
        print("=" * 70)

        try:

            html = load_document(path)

            response = review_with_superdocs(
                document_name,
                html,
            )

            result = {
                "document": document_name,
                "filename": filename,
                "status": "REVIEWED",
                "response": response,
            }

            print_proposed_changes(
                response
            )

            updated_html = extract_updated_html(
                response
            )

            # ------------------------------------------------
            # If SuperDocs returned completed HTML directly,
            # save it.
            # ------------------------------------------------

            if updated_html:

                print(
                    "\n✓ SuperDocs returned updated HTML."
                )

                save_document(
                    path,
                    updated_html,
                )

                result["status"] = "UPDATED"

                print(
                    f"✓ Saved: {path}"
                )

            else:

                print(
                    "\n✓ SuperDocs completed the style review."
                )

                print(
                    "No directly-applied HTML was returned."
                )

                print(
                    "Review proposed changes before approval."
                )

            results.append(result)

        except Exception as exc:

            print(
                f"\n✗ House-style review failed: {exc}"
            )

            results.append(
                {
                    "document": document_name,
                    "filename": filename,
                    "status": "FAILED",
                    "error": str(exc),
                }
            )

    # ========================================================
    # SAVE AUDIT REPORT
    # ========================================================

    OUTPUT_FILE.write_text(
        json.dumps(
            {
                "report_title": REPORT_TITLE,
                "session_id": SESSION_ID,
                "documents": results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print("SUPERDOCS HOUSE STYLE REVIEW COMPLETE")
    print("=" * 70)

    for result in results:

        print(
            f"{result['document']}: "
            f"{result['status']}"
        )

    print(
        f"\nReport saved: {OUTPUT_FILE}"
    )

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()