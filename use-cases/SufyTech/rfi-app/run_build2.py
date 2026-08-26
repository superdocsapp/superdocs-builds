"""
run_build2.py — Build 2: Procore/Autodesk-Construction RFI app, end to
end against the real SuperDocs API.

Requires a real SUPERDOCS_API_KEY environment variable.

The 4 required call types (upload, chat, approve, export) all happen in
this one flow, in this order:
  1. upload   — draft the initial formal RFI document from a fictional
     Procore/Autodesk-shaped payload (construction_data.fetch_open_rfi())
  2. chat_async + approve — a second, later event: the architect's
     response arrives (construction_data.fetch_rfi_response_event()).
     Sent as a targeted edit instruction, reviewed before it lands
     (HITL) — mirroring Build 1's "initial state, then one real
     targeted update" shape, which is what proves this build handles a
     genuine update, not just a one-shot document generation.
  3. export   — download the finished, answered RFI as .docx

Reuses superdocs_client.SuperDocsClient exactly as fixed and live-
verified in Build 1 (session-per-run, wait_for_job's in_progress fix,
the documented single-vs-batch /approve payload shapes, the export-
staleness fix) rather than re-deriving any of that here - those are
confirmed facts about the live API, not guesses to redo per build.
"""

from __future__ import annotations

import os
import sys
import uuid

import requests
from dotenv import load_dotenv
load_dotenv()
from construction_data import fetch_open_rfi, fetch_rfi_response_event
from document_builder import build_rfi_document_html
from rfi_patch import patch_response_fields
from superdocs_client import SuperDocsClient

SESSION_ID = f"rfi-build2-{uuid.uuid4().hex[:8]}"


def main() -> None:
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        print("SUPERDOCS_API_KEY is not set. Get a key from use.superdocs.app -> Settings -> API Keys,")
        print('then: $env:SUPERDOCS_API_KEY="sk_..."   (PowerShell)')
        sys.exit(1)

    client = SuperDocsClient(api_key=api_key)

    # --- Step 1: draft and upload the initial open RFI -----------------
    print("[1/4] Fetching the open RFI (fictional Procore/Autodesk-shaped payload)...")
    rfi = fetch_open_rfi()
    print(f"    RFI number: {rfi.rfi_number}")
    print(f"    Spec section: {rfi.spec_section}")
    print(f"    Drawing reference: {rfi.drawing_reference}")

    print("[1/4] Building and uploading the initial RFI document...")
    initial_html = build_rfi_document_html(rfi)
    client.upload_document_html_as_base64(
        html=initial_html, filename="rfi-0142.html", session_id=SESSION_ID
    )
    print(f"    SESSION_ID: {SESSION_ID}")

    print("    verifying the upload actually landed before proceeding...")
    client.wait_for_upload_to_settle(SESSION_ID, expected_marker=rfi.rfi_number)
    print("    confirmed: session document contains the uploaded RFI.")

    # --- Step 2/3: the architect's response arrives ---------------------
    print("[2/4] Fetching the architect's response event...")
    response_event = fetch_rfi_response_event()
    print(f"    status: {response_event['status']}")

    edit_message = (
        f"The architect has responded to {rfi.rfi_number}. Update ONLY the Response "
        f"section to reflect this - do not touch the Question, Spec Section, or "
        f"Drawing Reference fields, and do not paraphrase the response text:\n\n"
        f"- Status: {response_event['status']}\n"
        f"- Responded By: {response_event['responded_by']}\n"
        f"- Date Responded: {response_event['date_responded']}\n"
        f"- Cost Impact: {response_event['cost_impact']}\n"
        f"- Schedule Impact: {response_event['schedule_impact']}\n"
        f"- Response: {response_event['response']}"
    )

    print("[2/4] Starting the targeted response edit (chat_async, HITL approval)...")
    async_result = client.chat_async(
        session_id=SESSION_ID, message=edit_message, approval_mode="ask_every_time"
    )
    job_id = async_result["job_id"]
    print(f"    job started: {job_id}")

    job = client.wait_for_job(job_id)
    pending_changes = job.get("metadata", {}).get("pending_changes") or []
    print(f"    job status={job.get('status')}, {len(pending_changes)} change(s) awaiting approval")

    if job.get("status") == "awaiting_approval" and pending_changes:
        approve_result = client.approve_changes(
            session_id=SESSION_ID, job_id=job_id, change_records=pending_changes, approved=True
        )
        print(f"    approved {len(pending_changes)} change(s) via {approve_result['mode']} mode")
        job = client.wait_for_job(job_id)
        print(f"    final job status: {job['status']}")
    elif job.get("status") == "failed":
        raise RuntimeError(f"Response edit job {job_id} failed server-side: {job.get('error') or job}")
    elif not pending_changes:
        raise RuntimeError(
            f"Response edit job {job_id} settled with status={job.get('status')!r} and no "
            f"pending_changes. Refusing to export, since there's nothing to verify was "
            f"applied - same fail-closed rule as Build 1."
        )

    # --- Step 4: verify, force-patch, export ----------------------------
    print("[4/4] Verifying the approved change(s) actually landed before exporting...")
    if pending_changes:
        verified_html = client.verify_and_get_final_html(SESSION_ID, pending_changes)
    else:
        verified_html = client.get_session_history(SESSION_ID)["document_state"]["html_content"]

    print("[4/4] Forcing Response fields to match the known-correct response event...")
    if len(pending_changes) != 1:
        raise RuntimeError(
            f"Expected exactly 1 pending change to force-patch the Response block, got "
            f"{len(pending_changes)}. Refusing to guess which chunk_id is the right one."
        )
    response_chunk_id = pending_changes[0]["chunk_id"]
    verified_html = patch_response_fields(verified_html, response_event, response_chunk_id)

    output = client.export_html(
        verified_html, output_path="rfi-0142-answered.docx", filename="rfi-0142-answered"
    )
    print(f"    saved: {output}")

    print("\nDone. One file written to the current directory:")
    print("  - rfi-0142-answered.docx")


if __name__ == "__main__":
    main()
