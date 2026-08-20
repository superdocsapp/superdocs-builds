"""
build_with_approval.py — human-in-the-loop expansion via
/v1/chat/async + approval_mode='ask_every_time'.

Two real bugs found and fixed while building this:
1. The approve endpoint distinguishes single-change vs batch decision
   shape (per docs), but ALSO requires job_id in the body regardless
   of shape - not stated in the endpoint description, only discovered
   via a 422 validation error naming the missing field directly.
2. cancel_job refuses jobs in awaiting_approval status ("Job cannot be
   cancelled"), which directly contradicts the 409 session_busy
   error's own suggested_action ("cancel it with cancel_job"). The
   real fix for a stuck awaiting_approval job is to resolve it through
   approve, not cancel - both worth reporting to SuperDocs.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import time
import json
from pathlib import Path

import requests

from extract_content import extract_text, extract_palette

DESIGN_ID = "DAHSiXKMgD4"
ASSET_DIR = Path("design_assets") / DESIGN_ID
API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
SESSION_ID = f"canva-approval-{DESIGN_ID}-v2"  # fresh session, avoids any leftover state


def poll_job(job_id: str) -> dict:
    if not job_id:
        raise ValueError("No job_id to poll - the async call itself failed. Check the response body above.")
    print("Polling job status...")
    for attempt in range(60):
        response = requests.get(f"https://api.superdocs.app/v1/jobs/{job_id}", headers=HEADERS)
        data = response.json()
        status = data.get("status")
        print(f"  attempt {attempt+1}: status={status}")
        if status in ("awaiting_approval", "completed", "failed", "cancelled"):
            return data
        time.sleep(3)
    raise TimeoutError("Job did not reach a decidable state in time")


def review_changes(pending_changes: list[dict]) -> list[dict]:
    decisions = []
    for i, change in enumerate(pending_changes, start=1):
        print(f"\n--- Proposed change {i}/{len(pending_changes)} ---")
        print(f"chunk_id: {change.get('chunk_id')}")
        print(f"AI explanation: {change.get('ai_explanation', '(none)')}")
        old_html = change.get("old_html") or "(new content)"
        new_html = change.get("new_html") or "(none)"
        print(f"OLD: {old_html[:200]}")
        print(f"NEW: {new_html[:200]}")

        decision = input("Approve this change? [y/n]: ").strip().lower()
        decisions.append({"change_id": change.get("change_id"), "approved": decision == "y"})
    return decisions


def submit_decisions(job_id: str, decisions: list[dict]) -> requests.Response:
    if len(decisions) == 1:
        body = {"job_id": job_id, "approved": decisions[0]["approved"]}
    else:
        body = {"job_id": job_id, "changes": decisions}

    response = requests.post(
        f"https://api.superdocs.app/v1/chat/{SESSION_ID}/approve",
        headers=HEADERS,
        json=body,
    )
    print(f"Approve call status: {response.status_code}")
    if response.status_code != 200:
        print(f"Approve call error body: {response.text}")
    return response


def main():
    raw_text = extract_text(ASSET_DIR / "page_1.pdf")
    colors = extract_palette(ASSET_DIR / "page_1.png")
    color_list = ", ".join(colors)

    seed_html = "\n".join(f"<p>{line}</p>" for line in raw_text.split("\n") if line.strip())

    print("Seeding document...")
    requests.post(
        "https://api.superdocs.app/v1/chat",
        headers=HEADERS,
        json={
            "message": "Load this content as the starting document. Do not rewrite anything yet.",
            "session_id": SESSION_ID,
            "document_html": seed_html,
        },
    )

    instruction = (
        "This is the copy from a promotional flyer for 'ROOTED — Cold Brew', a clean-energy "
        "cold brew coffee product for trail runners. Expand this into a full one-page "
        "leave-behind report: add sections for 'Product Overview', 'Why Trail Runners Choose "
        "ROOTED', 'Event Marketing Calendar', and 'Contact & Ordering Information'. "
        f"Use {colors[0]} as the color for all section headings. Keep the tone energetic "
        "and outdoorsy. The brand's color palette is: " + color_list
    )

    print("\nSending expansion request via async + human approval...")
    response = requests.post(
        "https://api.superdocs.app/v1/chat/async",
        headers=HEADERS,
        json={
            "message": instruction,
            "session_id": SESSION_ID,
            "approval_mode": "ask_every_time",
        },
    )
    print(f"\nAsync call status: {response.status_code}")
    print(f"Raw response body: {response.text[:500]}")
    job_id = response.json().get("job_id")
    print(f"Job started: {job_id}")

    job_data = poll_job(job_id)
    status = job_data.get("status")

    if status != "awaiting_approval":
        print(f"\nUnexpected status '{status}' - nothing to review.")
        print(json.dumps(job_data, indent=2)[:1000])
        return

    pending_changes = job_data.get("metadata", {}).get("pending_changes", [])
    print(f"\n{len(pending_changes)} change(s) proposed, awaiting your review.")

    decisions = review_changes(pending_changes)
    submit_decisions(job_id, decisions)

    final_job = poll_job(job_id)
    print(f"\nFinal status: {final_job.get('status')}")

    final_html = final_job.get("document_html", "")
    if final_html:
        Path("output_with_approval.html").write_text(final_html, encoding="utf-8")
        print(f"Saved final document to output_with_approval.html ({len(final_html)} chars)")


if __name__ == "__main__":
    main()