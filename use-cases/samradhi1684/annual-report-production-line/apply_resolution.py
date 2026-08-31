import os
import json
import requests
from pathlib import Path


API_KEY = os.environ["SUPERDOCS_API_KEY"]

BASE_URL = "https://api.superdocs.app"

# Session containing the five annual-report documents.
SESSION_ID = "annual-report-2026"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

RESOLUTION_REPORT = Path("resolution-report.json")


# ============================================================
# LOCAL DOCUMENT MAPPING
# ============================================================

DOCUMENT_FILES = {
    "Chair Statement": Path("documents/chair-statement.html"),
    "Business Review": Path("documents/business-review.html"),
    "Strategy": Path("documents/strategy.html"),
    "Financial Statements": Path("documents/financial-statements.html"),
    "Governance": Path("documents/governance.html"),
}


# ============================================================
# LOAD RESOLUTION REPORT
# ============================================================

def load_resolution_report():
    if not RESOLUTION_REPORT.exists():
        raise FileNotFoundError(
            "resolution-report.json not found. "
            "Run resolution.py first."
        )

    with open(
        RESOLUTION_REPORT,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


# ============================================================
# GET LOCAL DOCUMENT PATH
# ============================================================

def get_document_path(document_name):
    path = DOCUMENT_FILES.get(document_name)

    if path is None:
        raise ValueError(
            f"No local file mapping found for "
            f"'{document_name}'.\n"
            f"Add it to DOCUMENT_FILES in apply_resolution.py."
        )

    if not path.exists():
        raise FileNotFoundError(
            f"Local document not found:\n"
            f"  {path}"
        )

    return path


# ============================================================
# GET LOCAL CONTEXT
# ============================================================

def get_local_context(resolution, context_chars=500):
    """
    Find the current value in the local target document and
    return surrounding HTML as context for SuperDocs.
    """

    document_name = resolution["document_to_review"]
    current_value = resolution["current_value"]

    path = get_document_path(document_name)

    html = path.read_text(encoding="utf-8")

    index = html.find(current_value)

    if index == -1:
        raise ValueError(
            f"Could not find '{current_value}' in "
            f"the target document:\n"
            f"  {path}"
        )

    start = max(0, index - context_chars)

    end = min(
        len(html),
        index + len(current_value) + context_chars,
    )

    return html[start:end]


# ============================================================
# UPDATE LOCAL HTML DOCUMENT
# ============================================================

def update_local_document(resolution):
    """
    Apply the approved change to the local HTML document.

    The replacement is deliberately strict:
    - exactly one occurrence must exist
    - otherwise nothing is changed
    """

    document_name = resolution["document_to_review"]
    current_value = resolution["current_value"]
    proposed_value = resolution["proposed_value"]

    path = get_document_path(document_name)

    html = path.read_text(encoding="utf-8")

    occurrence_count = html.count(current_value)

    if occurrence_count == 0:
        raise ValueError(
            f"Could not find the current value in the "
            f"target document.\n\n"
            f"Document:\n"
            f"  {path}\n\n"
            f"Value:\n"
            f"  {current_value}"
        )

    if occurrence_count > 1:
        raise ValueError(
            f"Found {occurrence_count} occurrences of "
            f"'{current_value}' in {path}.\n\n"
            f"The script will not perform an ambiguous "
            f"replacement."
        )

    updated_html = html.replace(
        current_value,
        proposed_value,
        1,
    )

    path.write_text(
        updated_html,
        encoding="utf-8",
    )

    # Verify the replacement.
    verification_html = path.read_text(
        encoding="utf-8"
    )

    if current_value in verification_html:
        raise RuntimeError(
            f"Verification failed: old value still exists "
            f"in {path}"
        )

    if proposed_value not in verification_html:
        raise RuntimeError(
            f"Verification failed: proposed value was not "
            f"found in {path}"
        )

    print("\n✓ Local document updated.")
    print(f"  Document: {document_name}")
    print(f"  File:     {path}")
    print(
        f"  Changed:  "
        f"{current_value} → {proposed_value}"
    )

    return path


# ============================================================
# SEND APPROVED CHANGE TO SUPERDOCS
# ============================================================

def apply_change(resolution, context):
    """
    Ask SuperDocs to apply the approved correction.

    The local document is passed as context so SuperDocs has
    an exact textual anchor rather than relying only on the
    human-readable document name.
    """

    authoritative_document = resolution[
        "authoritative_document"
    ]

    document_to_update = resolution[
        "document_to_review"
    ]

    concept = resolution["concept"]
    current_value = resolution["current_value"]
    proposed_value = resolution["proposed_value"]
    reason = resolution["reason"]

    prompt = f"""
You are applying an APPROVED correction to an annual report.

A human has already reviewed and explicitly approved this change.

DO NOT ask for clarification.
DO NOT merely describe what should be changed.
DO NOT provide a hypothetical answer.

Apply the edit to the target document.

==================================================
APPROVED CHANGE
==================================================

Authoritative document:
{authoritative_document}

Target document:
{document_to_update}

Concept:
{concept}

Current value:
{current_value}

Proposed value:
{proposed_value}

Reason:
{reason}

==================================================
TARGET DOCUMENT CONTEXT
==================================================

The following context comes from the local source file
for the target document. Use it to identify the exact
content that must be changed:

{context}

==================================================
EDIT INSTRUCTIONS
==================================================

1. Edit ONLY the target document:

   "{document_to_update}"

2. Locate the passage corresponding to:

   "{concept}"

3. In that passage, change:

   "{current_value}"

   to:

   "{proposed_value}"

4. Preserve the surrounding wording.

5. Preserve formatting and document structure.

6. Do NOT modify:

   "{authoritative_document}"

7. Do NOT modify any other document.

8. Do NOT change any other numbers.

9. Do NOT rewrite unrelated content.

10. Do NOT invent new content.

11. This is an already-approved editing operation.
    Apply the edit now.

12. After editing, verify that the target document contains
    the proposed value for this concept.

==================================================
RESPONSE REQUIREMENT
==================================================

If the edit was successfully applied, state clearly:

UPDATED

and explain briefly what changed.

If you could not locate the exact target content or could
not apply the edit, state clearly:

NOT_UPDATED

and explain why.

Do not claim that an edit was applied if it was not.
"""

    payload = {
        "message": prompt,
        "session_id": SESSION_ID,
        "approval_mode": "approve_all",
    }

    print("\nSending approved change to SuperDocs...")

    response = requests.post(
        f"{BASE_URL}/v1/chat",
        headers=HEADERS,
        json=payload,
        timeout=300,
    )

    print("Status:", response.status_code)

    response.raise_for_status()

    result = response.json()

    response_text = result.get(
        "response",
        "",
    )

    print("\n" + "-" * 70)
    print("SUPERDOCS RESPONSE")
    print("-" * 70)

    print(response_text)

    return response_text


# ============================================================
# CHECK SUPERDOCS RESPONSE
# ============================================================

def superdocs_confirmed_edit(response_text):
    """
    Determine whether SuperDocs explicitly reported that
    the edit was applied.
    """

    text = response_text.lower().strip()

    # Strong explicit failure signals.
    failure_phrases = [
        "not_updated",
        "could not",
        "couldn't",
        "unable",
        "not found",
        "cannot locate",
        "can't locate",
        "wasn't able",
        "not able",
        "no further updates",
        "already correctly",
        "already correct",
        "i'm not sure",
        "i am not sure",
        "could you clarify",
        "rephrase",
    ]

    for phrase in failure_phrases:
        if phrase in text:
            return False

    # Strong success signals.
    success_phrases = [
        "updated",
        "change applied",
        "edit applied",
        "successfully updated",
        "successfully applied",
        "replaced",
        "changed from",
    ]

    return any(
        phrase in text
        for phrase in success_phrases
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 70)
    print("ANNUAL REPORT RESOLUTION APPROVAL")
    print("=" * 70)

    report = load_resolution_report()

    resolutions = report.get(
        "resolutions",
        [],
    )

    actions = [
        resolution
        for resolution in resolutions
        if resolution.get("status") == "ACTION_REQUIRED"
    ]

    if not actions:
        print("\nNo resolution actions require approval.")
        return

    applied = 0
    rejected = 0
    failed = 0

    for index, resolution in enumerate(
        actions,
        start=1,
    ):

        print("\n" + "-" * 70)
        print(f"Resolution [{index}]")
        print("-" * 70)

        print("\nConcept:")
        print(f"  {resolution['concept']}")

        print("\nAuthoritative document:")
        print(
            f"  {resolution['authoritative_document']}"
        )

        print("\nDocument to review:")
        print(
            f"  {resolution['document_to_review']}"
        )

        print("\nCurrent value:")
        print(
            f"  {resolution['current_value']}"
        )

        print("\nProposed value:")
        print(
            f"  {resolution['proposed_value']}"
        )

        print("\nReason:")
        print(f"  {resolution['reason']}")

        print(
            "\nApprove this change? [y/N]: ",
            end="",
        )

        answer = input().strip().lower()

        if answer != "y":
            print("\n✗ Change rejected.")
            rejected += 1
            continue

        print("\n✓ Change approved.")

        try:

            # ------------------------------------------------
            # STEP 1: Validate the local target
            # ------------------------------------------------

            context = get_local_context(
                resolution
            )

            # ------------------------------------------------
            # STEP 2: Apply the approved change locally
            #
            # This is the source used by audit.py.
            # ------------------------------------------------

            update_local_document(
                resolution
            )

            # ------------------------------------------------
            # STEP 3: Ask SuperDocs to apply the same change
            # ------------------------------------------------

            response_text = apply_change(
                resolution,
                context,
            )

            # ------------------------------------------------
            # STEP 4: Report SuperDocs result
            # ------------------------------------------------

            if superdocs_confirmed_edit(
                response_text
            ):
                print(
                    "\n✓ SuperDocs reported that the "
                    "approved edit was applied."
                )
            else:
                print(
                    "\n⚠ SuperDocs did not clearly confirm "
                    "that the edit was applied."
                )

                print(
                    "  The local document WAS updated because "
                    "the approved change was successfully "
                    "written to the local source file."
                )

            # ------------------------------------------------
            # STEP 5: Count the resolution as applied
            # ------------------------------------------------

            applied += 1

            print(
                "\n✓ Resolution applied successfully."
            )

        except requests.RequestException as exc:

            print(
                "\n✗ SuperDocs request failed."
            )

            print(f"  {exc}")

            # IMPORTANT:
            #
            # At this point the local file may already have
            # been updated. We therefore report the failure
            # explicitly rather than pretending everything
            # succeeded.

            failed += 1

        except (
            ValueError,
            FileNotFoundError,
            RuntimeError,
        ) as exc:

            print(
                "\n✗ Resolution failed."
            )

            print(f"  {exc}")

            failed += 1

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print("RESOLUTION SUMMARY")
    print("=" * 70)

    print(
        f"Approved/applied: {applied}"
    )

    print(
        f"Rejected:         {rejected}"
    )

    print(
        f"Failed:           {failed}"
    )

    if applied:
        print("\nNext step:")
        print(
            "  Run audit.py again to verify "
            "the inconsistency."
        )

    elif failed:
        print(
            "\nNo resolution was fully applied."
        )

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()