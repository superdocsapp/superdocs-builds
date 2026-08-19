import json
import os
import requests
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("SUPERDOCS_API_KEY")
MCP_URL = os.getenv(
    "SUPERDOCS_MCP_URL",
    "https://api.superdocs.app/mcp/",
)

SESSION_ID = "clinical-correspondence-demo"


def mcp_request(request_id, method, params=None):
    """Send a JSON-RPC request to the SuperDocs MCP server."""

    if not API_KEY:
        raise RuntimeError("SUPERDOCS_API_KEY is missing.")

    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }

    if params is not None:
        payload["params"] = params

    response = requests.post(
        MCP_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json=payload,
        timeout=120,
    )

    response.raise_for_status()

    return response.json()


def call_tool(request_id, tool_name, arguments):
    """Call an MCP tool."""

    return mcp_request(
        request_id,
        "tools/call",
        {
            "name": tool_name,
            "arguments": arguments,
        },
    )


def load_encounter():
    """Load the fabricated encounter record."""

    with open(
        "synthetic_encounter.json",
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def extract_structured_content(response):
    """
    Extract structuredContent from an MCP tools/call response.
    """

    result = response.get("result", {})

    structured = result.get("structuredContent")

    if structured:
        return structured

    # Some MCP responses put the JSON inside content[0].text.
    content = result.get("content", [])

    for item in content:
        if item.get("type") == "text":
            text = item.get("text", "")

            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

    return result


def print_json(title, data):
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)
    print(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        )
    )


def main():

    encounter = load_encounter()

    print("Clinical Correspondence Pack")
    print("=" * 80)
    print("Synthetic demonstration record loaded.")
    print(f"Patient: {encounter['patient']['name']}")
    print(f"Record ID: {encounter['patient']['record_id']}")
    print(f"Encounter: {encounter['encounter']['date']}")
    print()

    # ------------------------------------------------------------------
    # 1. Initialize MCP
    # ------------------------------------------------------------------

    initialize = mcp_request(
        1,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {
                "name": "clinical-correspondence-pack",
                "version": "1.0.0",
            },
        },
    )

    print("MCP initialization successful.")

    # ------------------------------------------------------------------
    # 2. Ask SuperDocs to create the correspondence pack
    # ------------------------------------------------------------------

    instruction = """
Using ONLY the supplied synthetic encounter record, create a Clinical
Correspondence Pack containing exactly four sections:

1. Referral Letter
2. Discharge Summary
3. Results Letter to Patient
4. Prior-Authorisation Letter

This is a demonstration using fabricated data only.

Do not invent diagnoses, symptoms, medications, procedures, clinical
findings, test results, dates, insurance facts, or recommendations that
are not present in the supplied record.

Clearly preserve that this is a fabricated demonstration record.

REFERRAL LETTER:
Address the referral to Cardiology and use only the supplied reason
for referral: additional evaluation of reported reduced exercise
tolerance.

DISCHARGE SUMMARY:
This is an outpatient follow-up demonstration. Do not imply that the
patient was hospitalized or invent admission/discharge events.
Summarize only the supplied encounter information.

RESULTS LETTER:
Write this in plain language for the patient. Explain the supplied
Complete Blood Count and Basic Metabolic Panel results using only the
information provided in the record. Do not introduce additional medical
interpretations.

PRIOR-AUTHORISATION LETTER:
Address the request to the supplied insurance provider. Use only the
provided member ID, requested service, and medical-necessity summary.

SIGN-OFF:
The clinician sign-off is required but remains pending human approval.
Do not represent the document as finally signed.

Preserve the distinction between demonstration information and real
clinical information.
"""

    # Put the encounter into the prompt as JSON.
    instruction += """

SOURCE ENCOUNTER RECORD:

""" + json.dumps(
        encounter,
        indent=2,
        ensure_ascii=False,
    )

    chat_response = call_tool(
        2,
        "chat",
        {
            "message": instruction,
            "session_id": SESSION_ID,

            # Important for medical/regulated workflows:
            # changes should require human review.
            "approval_mode": "ask_every_time",

            "model_tier": "pro",
            "thinking_depth": "deep",

            # Small demonstration document, so full response is useful.
            "response_mode": "full",
        },
    )

    chat_result = extract_structured_content(chat_response)

    print_json(
        "SUPERDOCS CHAT RESPONSE",
        chat_result,
    )

    # ------------------------------------------------------------------
    # 3. Check whether SuperDocs returned pending changes
    # ------------------------------------------------------------------

    document_changes = chat_result.get(
        "document_changes"
    )

    if not document_changes:
        print()
        print(
            "No document changes were returned."
        )
        print(
            "Review the SuperDocs response above."
        )
        return

    pending_changes = document_changes.get(
        "pending_changes"
    )

    if not pending_changes:
        print()
        print(
            "No pending changes were returned."
        )
        return

    print()
    print("=" * 80)
    print("HUMAN APPROVAL REQUIRED")
    print("=" * 80)

    for index, change in enumerate(
        pending_changes,
        start=1,
    ):
        print()
        print(f"Change #{index}")
        print(f"Change ID: {change.get('change_id')}")
        print(f"Operation: {change.get('operation')}")
        print(f"Chunk ID: {change.get('chunk_id')}")
        print(
            f"Explanation: "
            f"{change.get('ai_explanation')}"
        )

    # ------------------------------------------------------------------
    # 4. Ask the human whether to approve
    # ------------------------------------------------------------------

    print()
    answer = input(
        "Approve these document changes? [y/N]: "
    ).strip().lower()

    approved = answer == "y"

    # ------------------------------------------------------------------
    # 5. Approve / deny all changes
    # ------------------------------------------------------------------

    approval_response = call_tool(
        3,
        "approve_change",
        {
            "session_id": SESSION_ID,
            "job_id": chat_result.get("job_id", ""),
            "approved": approved,
            "changes": [
                {
                    "change_id": change.get(
                        "change_id"
                    ),
                    "approved": approved,
                    "feedback": (
                        None
                        if approved
                        else
                        "Human reviewer did not approve "
                        "these changes."
                    ),
                }
                for change in pending_changes
            ],
        },
    )

    approval_result = extract_structured_content(
        approval_response
    )

    print_json(
        "APPROVAL RESULT",
        approval_result,
    )

    if not approved:
        print()
        print(
            "Document changes were not approved."
        )
        return

    # ------------------------------------------------------------------
    # 6. Export the approved document as DOCX
    # ------------------------------------------------------------------

    export_response = call_tool(
        4,
        "export_document",
        {
            "session_id": SESSION_ID,
            "format": "docx",
            "options": {
                "paper_size": "A4",
                "orientation": "portrait",
                "margins": "normal",
                "filename": (
                    "clinical-correspondence-pack"
                ),
            },
        },
    )

    export_result = extract_structured_content(
        export_response
    )

    print_json(
        "DOCX EXPORT",
        export_result,
    )

    print()
    print("=" * 80)
    print("CLINICAL CORRESPONDENCE PACK COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()