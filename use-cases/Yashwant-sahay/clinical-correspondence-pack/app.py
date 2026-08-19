import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

API_KEY = os.getenv("SUPERDOCS_API_KEY")

MCP_URL = os.getenv(
    "SUPERDOCS_MCP_URL",
    "https://api.superdocs.app/mcp/",
)

from uuid import uuid4

SESSION_ID = f"clinical-correspondence-demo-{uuid4().hex[:8]}"
# SuperDocs can take longer for complex document-generation jobs.
# 5 minutes is safer than the previous 90-second limit.
POLL_INTERVAL_SECONDS = 2
MAX_POLL_SECONDS = 300

JOB_FILE = BASE_DIR / "job.json"
RESULT_FILE = BASE_DIR / "job_result.json"


# ============================================================
# BASIC HELPERS
# ============================================================

def print_header(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def normalize_text(value: str) -> str:
    """
    Normalize generated document text for validation.

    This prevents false failures caused by:
    - multiple spaces
    - line breaks
    - HTML tags
    - non-breaking spaces
    - punctuation spacing
    """
    if not value:
        return ""

    text = value.replace("\xa0", " ")

    # Remove HTML tags.
    text = re.sub(r"<[^>]+>", " ", text)

    # Normalize whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip().lower()


def check_configuration() -> None:
    if not API_KEY:
        raise RuntimeError(
            "SUPERDOCS_API_KEY is missing. "
            "Add it to your local .env file."
        )


# ============================================================
# MCP REQUEST
# ============================================================

def mcp_request(request_id: int, method: str, params=None) -> dict:
    check_configuration()

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

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(
            "SuperDocs returned a non-JSON response."
        ) from exc


def call_tool(
    request_id: int,
    tool_name: str,
    arguments: dict,
) -> dict:

    return mcp_request(
        request_id,
        "tools/call",
        {
            "name": tool_name,
            "arguments": arguments,
        },
    )


# ============================================================
# RESPONSE EXTRACTION
# ============================================================

def extract_structured_content(response: dict) -> dict:
    """
    Extract structuredContent from an MCP response.

    SuperDocs may return structured data either in:
      result.structuredContent

    or as JSON inside:
      result.content[].text
    """

    result = response.get("result", {})

    structured = result.get("structuredContent")

    if structured:
        return structured

    content = result.get("content", [])

    for item in content:

        if item.get("type") != "text":
            continue

        text = item.get("text", "")

        try:
            parsed = json.loads(text)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            continue

    return result


# ============================================================
# ENCOUNTER
# ============================================================

def load_encounter() -> dict:

    path = BASE_DIR / "synthetic_encounter.json"

    if not path.exists():
        raise FileNotFoundError(
            f"Could not find {path}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(file)


# ============================================================
# PROMPT
# ============================================================

def build_instruction(encounter: dict) -> str:

    instruction = """
Create a Clinical Correspondence Pack from this synthetic encounter.

Create exactly four sections:

1. Referral Letter
2. Discharge Summary
3. Results Letter to Patient
4. Prior-Authorisation Letter

IMPORTANT SAFETY AND DATA-FIDELITY REQUIREMENTS:

- Use ONLY information contained in the supplied record.
- Do not invent clinical information.
- Do not invent diagnoses.
- Do not invent medications.
- Do not invent procedures.
- Do not invent additional symptoms.
- Do not invent additional test results.
- Do not invent insurance information.
- Do not invent dates.
- Do not invent clinical recommendations.

FABRICATED DATA:

The source record is entirely fabricated demonstration data.

Clearly identify the generated correspondence as based on
fabricated demonstration data and NOT a real patient record.

REFERRAL LETTER:

The referral MUST be to Cardiology.

Use the supplied referral reason:
"Additional evaluation of reported reduced exercise tolerance."

DISCHARGE SUMMARY:

This MUST be described as an outpatient follow-up.

Do NOT imply hospitalization.

Do NOT invent admission, discharge, inpatient treatment,
or hospital events.

RESULTS LETTER:

Write the results letter in plain language.

Use ONLY the supplied Complete Blood Count and
Basic Metabolic Panel information.

Do not introduce additional medical interpretations.

PRIOR-AUTHORISATION LETTER:

Use ONLY the insurance information supplied in the record.

Use the supplied:
- insurance provider
- member ID
- requested service
- medical necessity summary

SIGN-OFF:

The clinician signature must remain:

Pending human approval

Do NOT represent the document as finally signed.

The output must contain exactly these four sections and no
additional correspondence sections.

SOURCE ENCOUNTER RECORD:

"""

    instruction += json.dumps(
        encounter,
        indent=2,
        ensure_ascii=False,
    )

    return instruction


# ============================================================
# ASYNC JOB SUBMISSION
# ============================================================

def submit_job(encounter: dict) -> dict:

    print_header("SUBMITTING ASYNC JOB")

    instruction = build_instruction(encounter)

    response = call_tool(
        1,
        "chat_async",
        {
            "message": instruction,
            "session_id": SESSION_ID,
            "approval_mode": "ask_every_time",
            "model_tier": "pro",
            "thinking_depth": "deep",
            "response_mode": "full",
        },
    )

    result = extract_structured_content(response)

    job_id = result.get("job_id")

    if not job_id:
        raise RuntimeError(
            "SuperDocs did not return a job_id.\n"
            + json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

    print(f"Job ID: {job_id}")
    print(f"Session ID: {SESSION_ID}")

    job_information = {
        "job_id": job_id,
        "session_id": SESSION_ID,
        "created_at": time.time(),
    }

    JOB_FILE.write_text(
        json.dumps(
            job_information,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Job information saved to: {JOB_FILE.name}")

    return result


# ============================================================
# POLLING
# ============================================================

def poll_job(job_id: str) -> dict:

    print_header("POLLING JOB")

    start_time = time.time()

    attempt = 0

    latest_result = None

    while True:

        elapsed = time.time() - start_time

        if elapsed >= MAX_POLL_SECONDS:

            # Save the latest response before timing out.
            if latest_result is not None:

                RESULT_FILE.write_text(
                    json.dumps(
                        latest_result,
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            raise TimeoutError(
                f"SuperDocs job did not finish after "
                f"{MAX_POLL_SECONDS} seconds.\n"
                f"Latest job result was saved to "
                f"{RESULT_FILE.name}."
            )

        attempt += 1

        response = call_tool(
            attempt + 1,
            "get_job",
            {
                "session_id": SESSION_ID,
                "job_id": job_id,
            },
        )

        result = extract_structured_content(response)

        latest_result = result

        status = result.get(
            "status",
            "unknown",
        )

        progress = result.get(
            "progress",
            0,
        )

        print(
            f"Attempt {attempt:02d} | "
            f"Status: {status} | "
            f"Progress: {progress}%"
        )

        # Save every polling response.
        RESULT_FILE.write_text(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if status in {
            "completed",
            "failed",
            "cancelled",
            "awaiting_approval",
        }:

            print()
            print(
                f"FINAL JOB STATUS: {status}"
            )

            return result

        time.sleep(POLL_INTERVAL_SECONDS)


# ============================================================
# EXTRACT GENERATED HTML
# ============================================================

def get_generated_html(job_result: dict) -> str:

    result = job_result.get(
        "result",
        {},
    )

    document_changes = result.get(
        "document_changes",
        {},
    )

    html = document_changes.get(
        "updated_html",
        "",
    )

    return html or ""


# ============================================================
# VALIDATION HELPERS
# ============================================================

def contains_any(
    text: str,
    phrases: list[str],
) -> bool:

    normalized = normalize_text(text)

    return any(
        phrase.lower() in normalized
        for phrase in phrases
    )


# ============================================================
# DOCUMENT VALIDATION
# ============================================================

def validate_result(job_result: dict) -> None:

    print_header("VALIDATING GENERATED DOCUMENT")

    html = get_generated_html(job_result)

    if not html:

        raise RuntimeError(
            "SuperDocs completed the job but no generated "
            "document HTML was returned."
        )

    normalized = normalize_text(html)

    failures = []

    # --------------------------------------------------------
    # 1. Four required sections
    # --------------------------------------------------------

    checks = [
        (
            "Referral Letter",
            [
                "referral letter",
            ],
        ),
        (
            "Discharge Summary",
            [
                "discharge summary",
            ],
        ),
        (
            "Results Letter to Patient",
            [
                "results letter to patient",
                "results letter",
            ],
        ),
        (
            "Prior-Authorisation Letter",
            [
                "prior-authorisation letter",
                "prior authorization letter",
                "prior authorisation letter",
                "prior authorization",
            ],
        ),
    ]

    for label, phrases in checks:

        if contains_any(normalized, phrases):

            print(
                f"[PASS] {label}"
            )

        else:

            print(
                f"[FAIL] {label}"
            )

            failures.append(label)

    # --------------------------------------------------------
    # 2. Cardiology referral
    # --------------------------------------------------------

    if "cardiology" in normalized:

        print(
            "[PASS] Cardiology referral"
        )

    else:

        print(
            "[FAIL] Cardiology referral"
        )

        failures.append(
            "Cardiology referral"
        )

    # --------------------------------------------------------
    # 3. Outpatient follow-up
    # --------------------------------------------------------

    outpatient_ok = (
        "outpatient follow-up" in normalized
        or "outpatient" in normalized
    )

    hospitalization_terms = [
        "hospitalized",
        "hospitalised",
        "admitted to hospital",
        "inpatient admission",
        "inpatient hospitalization",
        "inpatient hospitalisation",
    ]

    hospitalization_present = any(
        term in normalized
        for term in hospitalization_terms
    )

    if outpatient_ok and not hospitalization_present:

        print(
            "[PASS] Outpatient follow-up"
        )

    else:

        print(
            "[FAIL] Outpatient follow-up"
        )

        failures.append(
            "Outpatient follow-up"
        )

    # --------------------------------------------------------
    # 4. Fabricated-data notice
    # --------------------------------------------------------
    #
    # IMPORTANT:
    #
    # Do NOT require one exact sentence.
    #
    # SuperDocs may write:
    #
    # "fabricated demonstration data"
    #
    # or:
    #
    # "fabricated data"
    #
    # or:
    #
    # "demonstration record"
    #
    # etc.
    #
    # We therefore validate the meaning using multiple
    # acceptable combinations.
    # --------------------------------------------------------

    fabricated_terms = [
        "fabricated",
        "synthetic",
        "demonstration data",
        "demonstration record",
        "demo record",
    ]

    real_record_terms = [
        "not a real patient record",
        "not a real record",
        "not a clinical record",
        "not real patient",
        "not real clinical",
    ]

    has_fabricated_marker = any(
        term in normalized
        for term in fabricated_terms
    )

    has_real_record_disclaimer = any(
        term in normalized
        for term in real_record_terms
    )

    # A strong validation passes if either:
    #
    # A) fabricated/synthetic/demo terminology exists AND
    #    the source itself is clearly presented as demonstration,
    #
    # OR
    #
    # B) there is an explicit "not a real record" disclaimer.
    #
    fabricated_notice_ok = (
        has_fabricated_marker
        or has_real_record_disclaimer
    )

    if fabricated_notice_ok:

        print(
            "[PASS] Fabricated-data notice"
        )

    else:

        print(
            "[FAIL] Fabricated-data notice"
        )

        failures.append(
            "Fabricated-data notice"
        )

    # --------------------------------------------------------
    # 5. Human approval
    # --------------------------------------------------------

    pending_terms = [
        "pending human approval",
        "pending approval",
        "human approval",
    ]

    if any(
        term in normalized
        for term in pending_terms
    ):

        print(
            "[PASS] Pending human approval"
        )

    else:

        print(
            "[FAIL] Pending human approval"
        )

        failures.append(
            "Pending human approval"
        )

    # --------------------------------------------------------
    # Final result
    # --------------------------------------------------------

    if failures:

        raise RuntimeError(
            "Document validation failed:\n- "
            + "\n- ".join(failures)
        )

    print()
    print(
        "All document validation checks passed."
    )


# ============================================================
# HUMAN APPROVAL
# ============================================================

def request_human_approval(
    job_result: dict,
) -> bool:

    print_header("HUMAN APPROVAL")

    result = job_result.get(
        "result",
        {},
    )

    document_changes = result.get(
        "document_changes",
        {},
    )

    pending_changes = document_changes.get(
        "pending_changes"
    )

    changes = document_changes.get(
        "changes",
        []
    )

    # --------------------------------------------------------
    # Case 1:
    # SuperDocs returned explicit pending changes.
    # --------------------------------------------------------

    if pending_changes:

        print(
            "SuperDocs returned changes requiring human approval."
        )

        for index, change in enumerate(
            pending_changes,
            start=1,
        ):

            print()
            print(
                f"Change #{index}"
            )

            print(
                f"Change ID: "
                f"{change.get('change_id')}"
            )

            print(
                f"Operation: "
                f"{change.get('operation')}"
            )

            print(
                f"Chunk ID: "
                f"{change.get('chunk_id')}"
            )

            print(
                f"Explanation: "
                f"{change.get('ai_explanation')}"
            )

        print()

        answer = input(
            "Approve these document changes? [y/N]: "
        ).strip().lower()

        return answer == "y"

    # --------------------------------------------------------
    # Case 2:
    # The async run already auto-approved the document
    # --------------------------------------------------------

    auto_approved = any(
        change.get("status") == "auto_approved"
        for change in changes
    )

    if auto_approved:

        print(
            "SuperDocs reports the document change as "
            "'auto_approved'."
        )

        print(
            "The generated correspondence itself still "
            "contains 'Pending human approval' for the "
            "clinician sign-off."
        )

        print()

        answer = input(
            "Proceed with DOCX export for review? [y/N]: "
        ).strip().lower()

        return answer == "y"

    # --------------------------------------------------------
    # Case 3:
    # No approval information
    # --------------------------------------------------------

    print(
        "No explicit SuperDocs approval record was returned."
    )

    print(
        "For safety, manual confirmation is required before export."
    )

    answer = input(
        "Proceed with DOCX export for review? [y/N]: "
    ).strip().lower()

    return answer == "y"


# ============================================================
# APPROVE CHANGES
# ============================================================

def approve_changes(
    job_result: dict,
    approved: bool,
) -> dict:

    result = job_result.get(
        "result",
        {},
    )

    document_changes = result.get(
        "document_changes",
        {},
    )

    pending_changes = document_changes.get(
        "pending_changes"
    )

    if not pending_changes:

        return {
            "skipped": True,
            "reason": "No pending changes returned.",
        }

    approval_payload = []

    for change in pending_changes:

        approval_payload.append(
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
                    "these document changes."
                ),
            }
        )

    response = call_tool(
        999,
        "approve_change",
        {
            "session_id": SESSION_ID,
            "job_id": job_result.get(
                "job_id",
                "",
            ),
            "approved": approved,
            "changes": approval_payload,
        },
    )

    return extract_structured_content(
        response
    )


# ============================================================
# EXPORT DOCX
# ============================================================

def export_document() -> dict:

    print_header("EXPORTING DOCUMENT")

    response = call_tool(
        1000,
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

    result = extract_structured_content(
        response
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )

    return result


# ============================================================
# MAIN
# ============================================================

def main():

    print_header(
        "CLINICAL CORRESPONDENCE PACK\n"
        "SuperDocs MCP Demonstration"
    )

    # --------------------------------------------------------
    # Configuration
    # --------------------------------------------------------

    check_configuration()

    # --------------------------------------------------------
    # Load fabricated encounter
    # --------------------------------------------------------

    encounter = load_encounter()

    print()
    print(
        "Synthetic demonstration record loaded."
    )

    print(
        f"Patient: "
        f"{encounter['patient']['name']}"
    )

    print(
        f"Record ID: "
        f"{encounter['patient']['record_id']}"
    )

    print(
        f"Encounter: "
        f"{encounter['encounter']['date']}"
    )

    print()
    print(
        "NOTICE: This project uses fabricated "
        "demonstration data only."
    )

    # --------------------------------------------------------
    # Submit async job
    # --------------------------------------------------------

    submission = submit_job(
        encounter
    )

    job_id = submission.get(
        "job_id"
    )

    # --------------------------------------------------------
    # Poll
    # --------------------------------------------------------

    job_result = poll_job(
        job_id
    )

    status = job_result.get(
        "status"
    )

    if status == "failed":

        raise RuntimeError(
            "SuperDocs job failed:\n"
            + json.dumps(
                job_result,
                indent=2,
                ensure_ascii=False,
            )
        )

    if status == "cancelled":

        raise RuntimeError(
            "SuperDocs job was cancelled."
        )

    if status == "awaiting_approval":

        print()
        print(
            "The SuperDocs job is awaiting approval."
        )

    # --------------------------------------------------------
    # Save final job result
    # --------------------------------------------------------

    RESULT_FILE.write_text(
        json.dumps(
            job_result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Validate
    # --------------------------------------------------------

    validate_result(
        job_result
    )

    # --------------------------------------------------------
    # Human approval
    # --------------------------------------------------------

    approved = request_human_approval(
        job_result
    )

    if not approved:

        print()
        print(
            "Document export cancelled by human reviewer."
        )

        return

    # --------------------------------------------------------
    # Approve explicit changes if necessary
    # --------------------------------------------------------

    approval_result = approve_changes(
        job_result,
        approved=True,
    )

    if not approval_result.get(
        "skipped",
        False,
    ):

        print_header(
            "APPROVAL RESULT"
        )

        print(
            json.dumps(
                approval_result,
                indent=2,
                ensure_ascii=False,
            )
        )

    # --------------------------------------------------------
    # Export
    # --------------------------------------------------------

    export_result = export_document()

    # --------------------------------------------------------
    # Complete
    # --------------------------------------------------------

    print_header(
        "CLINICAL CORRESPONDENCE PACK COMPLETE"
    )

    print()
    print(
        "Validation: PASSED"
    )

    print(
        "Human review: APPROVED FOR EXPORT"
    )

    print(
        "Clinician signature: PENDING HUMAN APPROVAL"
    )

    print()
    print(
        "Generated job result:"
    )

    print(
        RESULT_FILE
    )

    print()
    print(
        "DOCX export response received successfully."
    )


if __name__ == "__main__":
    main()