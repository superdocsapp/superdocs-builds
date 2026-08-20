"""
Material-Change Analysis Between Versions
------------------------------------------
Use case: Legal & Procurement

Compares two versions of a (synthetic / non-confidential) contract via the
SuperDocs API, separates substantive changes from formatting noise,
identifies which party each change favors (liability, indemnification,
payment terms, etc.), and lists concrete pushback points a legal/procurement
reviewer could raise.

Hits exactly four SuperDocs endpoints, in order:
    1. Upload   -> send both contract versions
    2. Chat     -> instruct the AI to do the material-change comparison
    3. Approve  -> approve the returned findings/changes
    4. Export   -> export the final analysis

Handles three known developer traps:
    - The JSON Quirk: proposed-changes content comes back as a JSON-encoded
      *string* inside the response and needs a second parse.
    - The Timeout Trap: deep analysis can take 30s-several minutes with no
      visible progress. We poll patiently instead of failing fast.
    - The Budget Loop: SMALL_SAMPLE_MODE / MAX_OPERATIONS caps API usage
      while debugging.

NOTE: Endpoint paths/payload shapes below are written against the public
docs at docs.superdocs.app. Confirm exact field names there before running
against a live account -- adjust the constants in the CONFIG section if the
docs differ from what's assumed here.
"""

import json
import os
import time
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

# ----------------------------- CONFIG ------------------------------------

BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://docs.superdocs.app/api")
API_KEY = os.environ.get("SUPERDOCS_API_KEY")

SMALL_SAMPLE_MODE = os.environ.get("SMALL_SAMPLE_MODE", "true").lower() == "true"
MAX_OPERATIONS = int(os.environ.get("MAX_OPERATIONS", "5"))

POLL_INTERVAL_SECONDS = 5
MAX_POLL_MINUTES = 10  # generous ceiling; deep analysis can be slow (Timeout Trap)

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

COMPARISON_PROMPT = (
    "Compare version A and version B of this contract. "
    "Separate substantive/material changes from pure formatting or "
    "stylistic edits. For each material change, state which party "
    "(the party represented in version A, or the counterparty) the "
    "change favors and why — focus especially on liability shifts, "
    "indemnification scope changes, and payment term modifications. "
    "Finally, produce a list of concrete pushback points a reviewer "
    "on the disadvantaged side could raise in redlines or negotiation."
)


# --------------------------- BUDGET GUARD ---------------------------------

class OperationBudget:
    """Simple guard so debugging runs don't silently burn through API calls."""

    def __init__(self, max_ops: int, enabled: bool):
        self.max_ops = max_ops
        self.enabled = enabled
        self.count = 0

    def spend(self, label: str):
        self.count += 1
        if self.enabled and self.count > self.max_ops:
            raise RuntimeError(
                f"Budget exceeded: {self.count} operations attempted "
                f"(limit {self.max_ops}) while SMALL_SAMPLE_MODE is on. "
                f"Last attempted call: {label}. Raise MAX_OPERATIONS or "
                f"turn off SMALL_SAMPLE_MODE once you trust the flow."
            )
        print(f"  [budget] operation {self.count}/{self.max_ops if self.enabled else '∞'}: {label}")


budget = OperationBudget(MAX_OPERATIONS, SMALL_SAMPLE_MODE)


# ------------------------------ HELPERS ------------------------------------

def _require_api_key():
    if not API_KEY:
        sys.exit(
            "Missing SUPERDOCS_API_KEY. Copy .env.example to .env and fill "
            "in your key before running this script."
        )


def _double_parse_if_needed(value):
    """
    The JSON Quirk: SuperDocs sometimes returns proposed changes/findings as
    a JSON-encoded *string* nested inside the JSON response, rather than as
    a native object. If we get a string back where we expect an
    object/list, run json.loads() a second time.
    """
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            # It really was just a plain string -- return as-is.
            return value
    return value


def _post(path: str, payload: dict, label: str) -> dict:
    budget.spend(label)
    resp = requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _get(path: str, label: str) -> dict:
    budget.spend(label)
    resp = requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ------------------------------ STEP 1: UPLOAD ------------------------------

def upload_document(file_path: str, label: str) -> str:
    """Upload one contract version. Returns the SuperDocs document id."""
    budget.spend(f"upload:{label}")
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        headers = {"Authorization": HEADERS["Authorization"]}  # no JSON content-type on multipart
        resp = requests.post(f"{BASE_URL}/documents/upload", headers=headers, files=files, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    doc_id = data.get("document_id") or data.get("id")
    if not doc_id:
        raise RuntimeError(f"Upload response missing document id: {data}")
    print(f"Uploaded {label} -> document_id={doc_id}")
    return doc_id


# ------------------------------ STEP 2: CHAT --------------------------------

def request_comparison(doc_id_a: str, doc_id_b: str) -> str:
    """Send the material-change comparison instruction. Returns a job/session id to poll."""
    payload = {
        "document_ids": [doc_id_a, doc_id_b],
        "message": COMPARISON_PROMPT,
    }
    data = _post("/chat", payload, "chat:request_comparison")
    job_id = data.get("job_id") or data.get("session_id") or data.get("id")
    if not job_id:
        raise RuntimeError(f"Chat response missing job/session id: {data}")
    print(f"Comparison requested -> job_id={job_id}")
    return job_id


def poll_until_ready(job_id: str) -> dict:
    """
    The Timeout Trap: deep analysis can take 30s to several minutes with no
    visible progress. Poll patiently rather than failing fast.
    """
    deadline = time.time() + MAX_POLL_MINUTES * 60
    while time.time() < deadline:
        data = _get(f"/chat/{job_id}", "chat:poll_status")
        status = data.get("status", "unknown")
        print(f"  ...status: {status}")
        if status in ("complete", "completed", "done"):
            return data
        if status in ("failed", "error"):
            raise RuntimeError(f"Comparison job failed: {data}")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(
        f"Comparison job {job_id} did not complete within {MAX_POLL_MINUTES} minutes. "
        f"This may still be processing on SuperDocs' side -- check the dashboard "
        f"before assuming it crashed."
    )


def extract_findings(job_result: dict) -> dict:
    """Pull out the analysis payload, applying the double-JSON-parse fix."""
    raw = job_result.get("result") or job_result.get("changes") or job_result.get("content")
    findings = _double_parse_if_needed(raw)
    if findings is None:
        raise RuntimeError(f"No findings found in job result: {job_result}")
    return findings


# ------------------------------ STEP 3: APPROVE -----------------------------

def approve_findings(job_id: str, findings: dict) -> dict:
    """Programmatically approve the AI's findings to advance the workflow."""
    payload = {"job_id": job_id, "approved": True}
    data = _post("/approve", payload, "approve:findings")
    print("Findings approved.")
    return data


# ------------------------------ STEP 4: EXPORT ------------------------------

def export_analysis(job_id: str, export_format: str = "pdf") -> str:
    """Export the final analysis document and return the download URL."""
    payload = {"job_id": job_id, "format": export_format}
    data = _post("/export", payload, "export:analysis")
    export_url = data.get("export_url") or data.get("url")
    if not export_url:
        raise RuntimeError(f"Export response missing url: {data}")
    print(f"Exported -> {export_url}")
    return export_url


# ------------------------------ MAIN FLOW -----------------------------------

def main():
    _require_api_key()

    version_a_path = os.path.join("sample_data", "contract_v1.txt")
    version_b_path = os.path.join("sample_data", "contract_v2.txt")

    for p in (version_a_path, version_b_path):
        if not os.path.exists(p):
            sys.exit(
                f"Missing sample file: {p}\n"
                f"Drop two synthetic/public contract versions into sample_data/ "
                f"before running (never use real confidential paperwork)."
            )

    print("== Step 1: Upload ==")
    doc_id_a = upload_document(version_a_path, "version_a")
    doc_id_b = upload_document(version_b_path, "version_b")

    print("\n== Step 2: Chat (material-change comparison instruction) ==")
    job_id = request_comparison(doc_id_a, doc_id_b)
    job_result = poll_until_ready(job_id)
    findings = extract_findings(job_result)

    print("\n== Findings summary ==")
    print(json.dumps(findings, indent=2)[:2000])

    print("\n== Step 3: Approve ==")
    approve_findings(job_id, findings)

    print("\n== Step 4: Export ==")
    export_url = export_analysis(job_id)

    print(f"\nDone. Final analysis available at: {export_url}")


if __name__ == "__main__":
    main()
