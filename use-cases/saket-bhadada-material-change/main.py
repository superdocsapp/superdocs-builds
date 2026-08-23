"""
Material-Change Analysis Between Versions (REST API Pipeline)
------------------------------------------------------------
Built for the SuperDocs task.

Compares two versions of a contract via the SuperDocs REST API,
separates substantive changes from formatting noise, identifies which
party each change favors, and lists concrete pushback points.

4-Step API Flow:
    1. Upload   -> send both contract versions
    2. Chat     -> instruct the AI to perform material-change analysis
    3. Approve  -> programmatically approve the findings
    4. Export   -> export the final deliverable

Handles Founder Traps:
    - The JSON Quirk: Recursive double-parse unwraps nested JSON strings at all levels.
    - The Timeout Trap: Uses patient async polling instead of aggressive client timeouts.
    - The Budget Loop: SMALL_SAMPLE_MODE + MAX_OPERATIONS limits API consumption.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

# ----------------------------- CONFIG ------------------------------------

BASE_URL = os.environ.get("SUPERDOCS_BASE_URL", "https://docs.superdocs.app/api")
API_KEY = os.environ.get("SUPERDOCS_API_KEY")

SMALL_SAMPLE_MODE = os.environ.get("SMALL_SAMPLE_MODE", "true").lower() == "true"
MAX_OPERATIONS = int(os.environ.get("MAX_OPERATIONS", "5"))

POLL_INTERVAL_SECONDS = float(os.environ.get("POLL_INTERVAL_SECONDS", "5"))
MAX_POLL_MINUTES = int(os.environ.get("MAX_POLL_MINUTES", "10"))
OUTPUT_FILE = os.environ.get("EXPORT_FILENAME", "final_material_change_brief.md")

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

    def __init__(self, max_ops: int, enabled: bool) -> None:
        self.max_ops = max_ops
        self.enabled = enabled
        self.count = 0

    def spend(self, label: str) -> None:
        self.count += 1
        limit_str = str(self.max_ops) if self.enabled else "Unlimited"
        print(f"  [Budget Check] Operation {self.count}/{limit_str}: {label}")
        if self.enabled and self.count > self.max_ops:
            raise RuntimeError(
                f"Budget exceeded: {self.count} operations attempted "
                f"(limit {self.max_ops}) while SMALL_SAMPLE_MODE is on. "
                f"Last attempted call: {label}. Raise MAX_OPERATIONS or "
                f"turn off SMALL_SAMPLE_MODE once you trust the flow."
            )


budget = OperationBudget(MAX_OPERATIONS, SMALL_SAMPLE_MODE)


# --------------------------- RECURSIVE JSON PARSER ------------------------

def deep_parse(data: Any) -> Any:
    """
    Recursively unwraps nested JSON-encoded strings at any depth.
    Protects against JSON-in-JSON strings inside dictionary and list structures.
    """
    if isinstance(data, str):
        trimmed = data.strip()
        if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
            try:
                parsed = json.loads(trimmed)
                return deep_parse(parsed)
            except json.JSONDecodeError:
                return data
        return data
    elif isinstance(data, dict):
        return {k: deep_parse(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [deep_parse(item) for item in data]
    return data


# ------------------------------ HELPERS ------------------------------------

def _require_api_key() -> None:
    key = os.environ.get("SUPERDOCS_API_KEY") or API_KEY
    if not key or key == "your_api_key_here":
        sys.exit(
            "[ERROR] Missing SUPERDOCS_API_KEY. Copy .env.example to .env and fill "
            "in your key before running this script."
        )


def _post(path: str, payload: dict, label: str) -> dict:
    budget.spend(label)
    # Generous HTTP read timeout to prevent premature network disconnects
    resp = requests.post(f"{BASE_URL}{path}", headers=HEADERS, json=payload, timeout=300)
    resp.raise_for_status()
    return deep_parse(resp.json())


def _get(path: str, label: str) -> dict:
    budget.spend(label)
    resp = requests.get(f"{BASE_URL}{path}", headers=HEADERS, timeout=300)
    resp.raise_for_status()
    return deep_parse(resp.json())


# ------------------------------ STEP 1: UPLOAD ------------------------------

def upload_document(file_path: str, label: str) -> str:
    """Upload one contract version. Returns the SuperDocs document id."""
    budget.spend(f"upload:{label}")
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        headers = {"Authorization": HEADERS["Authorization"]}
        resp = requests.post(f"{BASE_URL}/documents/upload", headers=headers, files=files, timeout=300)
    resp.raise_for_status()
    data = deep_parse(resp.json())
    doc_id = data.get("document_id") or data.get("id")
    if not doc_id:
        raise RuntimeError(f"Upload response missing document id: {data}")
    print("  [OK] Uploaded " + label + " -> document_id=" + str(doc_id))
    return doc_id


# ------------------------------ STEP 2: CHAT --------------------------------

def request_comparison(doc_id_a: str, doc_id_b: str) -> str:
    """Send the comparison instruction. Returns a job/session id to poll."""
    payload = {
        "document_ids": [doc_id_a, doc_id_b],
        "message": COMPARISON_PROMPT,
    }
    data = _post("/chat", payload, "chat:request_comparison")
    job_id = data.get("job_id") or data.get("session_id") or data.get("id")
    if not job_id:
        # If the endpoint executed synchronously and directly returned findings
        return data
    print("  [OK] Comparison requested -> job_id=" + str(job_id))
    return job_id


def poll_until_ready(job_id_or_data: Any) -> dict:
    """
    The Timeout Trap: deep analysis can take 30s to several minutes with no
    visible progress. Poll patiently rather than failing fast.
    """
    if isinstance(job_id_or_data, dict):
        # Result was returned synchronously
        return job_id_or_data

    job_id = str(job_id_or_data)
    deadline = time.monotonic() + MAX_POLL_MINUTES * 60
    while time.monotonic() < deadline:
        data = _get(f"/chat/{job_id}", "chat:poll_status")
        status = str(data.get("status", "unknown")).lower()
        print(f"  ... polling status: {status}")
        if status in ("complete", "completed", "done", "success"):
            return data
        if status in ("failed", "error"):
            raise RuntimeError(f"Comparison job failed: {data}")
        time.sleep(POLL_INTERVAL_SECONDS)

    raise TimeoutError(
        f"Comparison job {job_id} did not complete within {MAX_POLL_MINUTES} minutes. "
        f"Check dashboard or adjust MAX_POLL_MINUTES in .env."
    )


def extract_findings(job_result: dict) -> dict:
    """Extracts analysis findings and ensures full recursive parsing."""
    raw = job_result.get("result") or job_result.get("changes") or job_result.get("content") or job_result
    findings = deep_parse(raw)
    if findings is None:
        raise RuntimeError(f"No findings found in job result: {job_result}")
    return findings


# ------------------------------ STEP 3: APPROVE -----------------------------

def approve_findings(job_id_or_data: Any, findings: dict) -> dict:
    job_id = job_id_or_data if isinstance(job_id_or_data, str) else "job_latest"
    payload = {"job_id": job_id, "approved": True}
    data = _post("/approve", payload, "approve:findings")
    print("  [OK] Findings approved.")
    return data


# ------------------------------ STEP 4: EXPORT ------------------------------

def export_analysis(job_id_or_data: Any, export_format: str = "markdown") -> str:
    job_id = job_id_or_data if isinstance(job_id_or_data, str) else "job_latest"
    payload = {"job_id": job_id, "format": export_format}
    data = _post("/export", payload, "export:analysis")
    export_url = data.get("export_url") or data.get("url") or data.get("content")
    print("  [OK] Export completed.")
    return export_url or "Analysis export successful."


# ------------------------------ MAIN FLOW -----------------------------------

def main():
    _require_api_key()

    version_a_path = os.path.join("sample_data", "contract_v1.txt")
    version_b_path = os.path.join("sample_data", "contract_v2.txt")

    for p in (version_a_path, version_b_path):
        if not os.path.exists(p):
            sys.exit(
                f"Missing sample file: {p}\n"
                f"Drop synthetic contract versions into sample_data/."
            )

    print("\n" + "=" * 65)
    print("  SuperDocs REST Material-Change Analysis Pipeline")
    print("=" * 65)

    print("\n--> Step 1: Uploading baseline and revised contracts...")
    doc_id_a = upload_document(version_a_path, "version_a")
    doc_id_b = upload_document(version_b_path, "version_b")

    print("\n--> Step 2: Requesting comparison & material analysis...")
    job_ref = request_comparison(doc_id_a, doc_id_b)
    job_result = poll_until_ready(job_ref)
    findings = extract_findings(job_result)

    print("\n--> Step 3: Approving findings...")
    approve_findings(job_ref, findings)

    print("\n--> Step 4: Exporting analysis deliverable...")
    export_res = export_analysis(job_ref)

    # Persist deliverable to output file
    out_file = Path(OUTPUT_FILE)
    out_content = (
        export_res if isinstance(export_res, str) and len(export_res) > 20
        else json.dumps(findings, indent=2)
    )
    out_file.write_text(out_content, encoding="utf-8")
    print(f"\n[OK] Analysis deliverable saved to: {out_file.resolve()}")
    print("\n" + "=" * 65 + "\n")


if __name__ == "__main__":
    main()
