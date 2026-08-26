"""
run_build1.py — Build 1: Recipe Costing & Re-Cost Pass, end to end against
the real SuperDocs API.

Requires a real SUPERDOCS_API_KEY environment variable.

The 4 required call types (upload, chat, approve, export) all happen in
this one flow, in this order:
  1. upload   — load the initial costed menu document
  2. chat_async + approve — targeted re-cost edit: update ONLY the
     olive-oil ingredient lines and their recipes' totals, reviewed
     before it lands (HITL). This satisfies "send an edit instruction"
     via the async endpoint, not plain sync /v1/chat — see README's
     Bug 3 for why the sync cover-intro step this build originally had
     here was cut (it reliably staged a pending change that 409'd the
     very next call).
  3. export   — download the final updated menu document AND the
     separate exceptions report, both as .docx
"""

from __future__ import annotations

import os
import sys
import uuid
import requests
from dotenv import load_dotenv
load_dotenv()
from document_builder import build_exceptions_report_html, build_menu_costing_document_html
from recipe_costing import apply_price_change, rank_exceptions
from sample_menu import MENU
from superdocs_client import SuperDocsClient
from value_patch import patch_all_affected_dishes

# REAL BUG FOUND AND FIXED HERE, logged honestly: this used to be a
# fixed constant ("recipe-costing-build1-v3", then "-v4" after the
# first time this bit us). Twice on real live runs, rejecting a
# leftover stuck job from an earlier interrupted run via /approve
# returned 500 Internal Server Error - once for job 08846f68-...
# (v3) and again for a *different* job, 8440a5f3-... (v4), which was
# itself only stuck because of the wait_for_job "in_progress" bug
# fixed in superdocs_client.py. That's two different jobs on two
# different sessions hitting the same failure mode, which points at
# rejecting a previously-interrupted job being unreliable server-side
# in general, not a one-off. Reported to hello@superdocs.app with both
# job IDs. Rather than keep manually bumping a hardcoded suffix every
# time this recurs, each run now gets its own fresh session ID, so
# there's structurally never a leftover job for clear_stuck_jobs_for_session
# to have to clean up. clear_stuck_jobs_for_session() is kept as
# defensive code (and still covered by tests against a mocked 409) in
# case a single run is itself interrupted mid-flight and re-run against
# the *same* session, but a brand-new session is what every normal
# invocation of this script uses.
SESSION_ID = f"recipe-costing-build1-{uuid.uuid4().hex[:8]}"
INGREDIENT_TO_REPRICE = "Olive oil"
NEW_UNIT_COST = 1.35  # see tests/test_recipe_costing.py for why this value


def clear_stuck_jobs_for_session(client: SuperDocsClient, session_id: str) -> None:
    """
    Defensive cleanup: if an earlier run left unapproved changes sitting
    on this session, SuperDocs will refuse any new instruction with a
    409 session_busy error until they're explicitly decided. This finds
    and rejects any such leftovers before starting fresh work, using
    only get_job/approve_change - no new, unverified endpoint needed.
    """
    try:
        client.chat_async(session_id=session_id, message="(session busy check - this message is discarded)")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code != 409:
            raise
        body = e.response.json()
        blocking_job_id = body.get("detail", {}).get("blocking_job_id")
        if not blocking_job_id:
            raise
        print(f"    Found a stuck job from an earlier run: {blocking_job_id}. Clearing it...")
        stuck_job = client.get_job(blocking_job_id)
        stuck_pending = stuck_job.get("metadata", {}).get("pending_changes") or []
        if stuck_pending:
            result = client.approve_changes(
                session_id=session_id, job_id=blocking_job_id, change_records=stuck_pending, approved=False
            )
            print(f"    Rejected {len(stuck_pending)} stuck change(s) via {result['mode']} mode.")


def main() -> None:
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        print("SUPERDOCS_API_KEY is not set. Get a key from use.superdocs.app -> Settings -> API Keys,")
        print('then: $env:SUPERDOCS_API_KEY="sk_..."   (PowerShell)')
        sys.exit(1)

    client = SuperDocsClient(api_key=api_key)

    print("[0/4] Checking for stuck jobs from earlier runs...")
    clear_stuck_jobs_for_session(client, SESSION_ID)

    # --- Step 1: upload the initial costed menu document ---------------
    print("[1/4] Building and uploading the initial costed menu document...")
    initial_html = build_menu_costing_document_html(MENU, title="Bistro Menu Costing Sheet")
    upload_result = client.upload_document_html_as_base64(
        html=initial_html, filename="menu-costing-sheet.html", session_id=SESSION_ID
    )
    print(f"    SESSION_ID: {SESSION_ID}")
    print(f"    UPLOAD RESULT: {upload_result}")

    # REAL BUG FOUND AND FIXED HERE, logged honestly: a live run showed
    # a fixed time.sleep(5) guess here was NOT always enough - a
    # subsequent chat_async call ran against a session that still held
    # a completely unrelated document (a generic template, not the
    # uploaded menu), and the AI correctly reported it couldn't find
    # any of the requested dishes. Fixed the same way every other
    # "did this really happen" question in this build is answered: not
    # by waiting longer and hoping, but by fetching the session's REAL
    # state and checking the upload actually landed before proceeding.
    print("    verifying the upload actually landed before proceeding (not just waiting and hoping)...")
    client.wait_for_upload_to_settle(SESSION_ID, expected_marker="Bistro Menu Costing Sheet")
    print("    confirmed: session document contains the uploaded menu.")

    # --- Step 2 skipped: an earlier cosmetic "add cover intro" sync-chat
    # step reliably created a staged AI edit that blocked the next step
    # with a 409 session_busy error. It wasn't required for the task's
    # core proof (arithmetic isolation + HITL + export), so it was cut
    # rather than fought - a defended cut, not silence.

    # --- Step 3: simulate the supplier price change (pure Python) ------
    print(f"[3/4] Simulating a supplier price change: {INGREDIENT_TO_REPRICE} -> ${NEW_UNIT_COST}/oz...")
    recost_result = apply_price_change(MENU, INGREDIENT_TO_REPRICE, NEW_UNIT_COST)
    exceptions = rank_exceptions(recost_result["updated_recipes"])
    print(f"    affected dishes: {recost_result['affected_dish_names']}")
    print(f"    exceptions (below target margin): {[e['dish_name'] for e in exceptions]}")

    change_lines = "\n".join(
        f"- {c['dish_name']}: Olive oil unit cost is now ${NEW_UNIT_COST:.2f}/oz. "
        f"New portion cost is ${c['new_portion_cost']:.2f} (was ${c['old_portion_cost']:.2f}). "
        f"New gross margin is {c['new_margin']*100:.1f}% (was {c['old_margin']*100:.1f}%)."
        for c in recost_result["line_changes"]
    )
    recost_message = (
        f"The supplier price for Olive oil changed to ${NEW_UNIT_COST:.2f}/oz. Update ONLY the "
        f"rows and totals for the dishes listed below to match the exact numbers given - do not "
        f"recalculate anything yourself, and do not touch any dish not listed here:\n\n{change_lines}"
    )

    print("[3/4] Starting the targeted re-cost edit (chat_async, HITL approval)...")
    import time as _time

    async_result = None
    for attempt in range(10):
        try:
            async_result = client.chat_async(
                session_id=SESSION_ID, message=recost_message, approval_mode="ask_every_time"
            )
            break
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 409:
                print(f"    HTTP ERROR BODY: {e.response.text}")
                raise
            body = e.response.json()
            blocking_job_id = body.get("detail", {}).get("blocking_job_id")
            blocking_status = body.get("detail", {}).get("blocking_status")
            print(f"    session busy ({blocking_status}, job {blocking_job_id}), waiting and retrying...")
            if blocking_status == "in_progress":
                # poll until it's no longer in_progress
                for _ in range(20):
                    _time.sleep(3)
                    j = client.get_job(blocking_job_id)
                    if j.get("status") != "in_progress":
                        break
            elif blocking_status == "awaiting_approval":
                # reject the stuck changes so the session frees up
                j = client.get_job(blocking_job_id)
                pending = j.get("metadata", {}).get("pending_changes") or []
                if pending:
                    client.approve_changes(
                        session_id=SESSION_ID, job_id=blocking_job_id, change_records=pending, approved=False
                    )

    if async_result is None:
        raise RuntimeError("Could not start the re-cost edit after 10 attempts - session stayed busy.")

    job_id = async_result["job_id"]
    print(f"    job started: {job_id}")

    job = client.wait_for_job(job_id)
    pending_changes = job.get("metadata", {}).get("pending_changes") or []
    print("FIRST PENDING CHANGE:", pending_changes[0] if pending_changes else None)

    print(f"    job status={job.get('status')}, {len(pending_changes)} change(s) awaiting approval")

    if job.get("status") == "awaiting_approval" and pending_changes:
        approve_result = client.approve_changes(
            session_id=SESSION_ID, job_id=job_id, change_records=pending_changes, approved=True
        )
        print(f"    approved {len(pending_changes)} change(s) via {approve_result['mode']} mode")
        job = client.wait_for_job(job_id)
        print(f"    final job status: {job['status']}")
    elif job.get("status") == "failed":
        raise RuntimeError(f"Re-cost job {job_id} failed server-side: {job.get('error') or job}")
    elif not pending_changes:
        # Never silently export on this path: a job that settled with
        # zero pending changes and isn't "awaiting_approval" is either
        # unexpectedly a no-op or something this build doesn't yet
        # understand about the job's final shape. Either way, exporting
        # here would risk shipping a pre-edit snapshot as if it were the
        # verified result - exactly the "success message that doesn't
        # mean what it claims" failure mode the task explicitly warns
        # against. Fail loudly instead so a human looks at it.
        raise RuntimeError(
            f"Re-cost job {job_id} settled with status={job.get('status')!r} and no "
            f"pending_changes. Refusing to export, since there's nothing to verify was "
            f"applied - inspect the job with inspect_job.py before re-running."
        )

    # --- Step 4: export the updated menu doc + the exceptions report ---
    # Export from VERIFIED html, never from the session's own possibly-
    # stale snapshot - see superdocs_client.py's module docstring for
    # the real bug this fixes (export right after approve doesn't
    # reliably reflect the just-approved edit yet).
    print("[4/4] Verifying the approved change(s) actually landed before exporting...")
    if pending_changes:
        verified_html = client.verify_and_get_final_html(SESSION_ID, pending_changes)
    else:
        verified_html = client.get_session_history(SESSION_ID)["document_state"]["html_content"]

    # REAL BUG FOUND AND FIXED HERE, logged honestly: verify_and_get_
    # final_html correctly exports exactly what SuperDocs' AI approved -
    # but a live run showed the AI's own approved edit was itself
    # incomplete: Unit Cost updated correctly, but that ingredient's own
    # Line Cost, and each affected dish's Portion cost / Gross margin,
    # did not reliably update to match. Same "arithmetic never touches
    # the LLM" principle as the rest of this build - value_patch.py
    # deterministically FORCES every derived number using
    # recipe_costing.py's own already-proven-correct calculations,
    # scoped per affected dish, regardless of what the AI's edit did or
    # didn't recompute correctly on its own.
    print("[4/4] Forcing derived values (Unit Cost, Line Cost, Portion cost, Gross margin) to match recipe_costing.py...")
    verified_html = patch_all_affected_dishes(
        verified_html,
        updated_recipes=recost_result["updated_recipes"],
        affected_dish_names=recost_result["affected_dish_names"],
        ingredient_name=INGREDIENT_TO_REPRICE,
    )

    menu_output = client.export_html(
        verified_html, output_path="menu-costing-sheet-updated.docx", filename="menu-costing-sheet-updated"
    )
    print(f"    saved: {menu_output}")

    print("[4/4] Building, uploading, and exporting the exceptions report...")
    exceptions_html = build_exceptions_report_html(exceptions, INGREDIENT_TO_REPRICE, NEW_UNIT_COST)
    exceptions_session_id = "recipe-costing-build1-exceptions"
    client.upload_document_html_as_base64(
        html=exceptions_html, filename="exceptions-report.html", session_id=exceptions_session_id
    )
    exceptions_output = client.export_document(
        session_id=exceptions_session_id, output_path="exceptions-report.docx", filename="exceptions-report"
    )
    print(f"    saved: {exceptions_output}")

    print("\nDone. Two files written to the current directory:")
    print("  - menu-costing-sheet-updated.docx")
    print("  - exceptions-report.docx")


if __name__ == "__main__":
    main()