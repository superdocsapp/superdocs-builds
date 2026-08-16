#!/usr/bin/env python3
"""
Owns one named SECTION of a standing SuperDocs document -- the heading
"[AGENT-MAINTAINED] Live Service Status" plus everything under it, down to
(not including) the next heading -- and keeps it current from a changing
external source (source_data/*.json, standing in for a real monitoring
feed), without ever touching the human-written sections above it.

A "section" is a heading chunk plus a variable number of content chunks
under it (a table, a status line), not a single chunk_id -- discovered by
inspecting a real created document (see PROGRESS.md): the table and the
"Last synced" line are each their own chunk, separate from the heading.
Ownership is tracked as the SET of chunk_ids in that section, re-derived by
searching the document's own structure each run rather than trusted blindly
from state, so a manually reorganized document is still handled correctly.

Run shape, every invocation:
  1. Compute a hash of the current source data.
  2. If it matches the hash from the last successful run: stop immediately.
     Zero API calls. This is the stopping rule, and it is also what makes
     the agent structurally incapable of re-triggering on its own output --
     it only ever reacts to the EXTERNAL source changing, never to the
     document changing, so its own edits can never be mistaken for new work.
  3. If the source changed and --preview is set: fetch the current document
     (a free read) and print what would change. No chat call, no approval,
     no cost -- verified for real by comparing whoami's monthly_used before
     and after (see PROOF_RUN.md).
  4. Otherwise: propose a change via chat_async(approval_mode="ask_every_time"),
     refuse to approve anything whose chunk_id falls outside the owned
     section, and after approval independently re-fetch the document and
     hash-compare every chunk OUTSIDE the section against a snapshot taken
     before the edit. If anything else moved, that's a hard failure, logged
     loudly -- not a warning, not swallowed.

Usage:
  python living_doc_agent.py --source source_data/status_v1.json [--preview] [--auto-approve]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from chunking import chunk_map_excluding, find_section_chunk_ids  # noqa: E402
from render import OWNED_SECTION_HEADING, render_section_instruction, source_hash  # noqa: E402
from superdocs_client import SuperDocsClient, SuperDocsError  # noqa: E402

STATE_FILE = Path(__file__).parent / "agent_state.json"

HUMAN_SECTION_1 = (
    "A level-2 heading exactly \"Weekly Priorities\", followed by a numbered list with these "
    "three items: \"Ship the Q3 customer portal redesign.\", \"Close out vendor renewal "
    "negotiations before end of month.\", \"Onboard two new SRE hires.\""
)
HUMAN_SECTION_2 = (
    "A level-2 heading exactly \"Team Notes\", followed by one paragraph: \"Standup moved to "
    "9:15am starting Monday. Ping Priya if you're out.\""
)


def log(msg: str) -> None:
    # SuperDocs' own response text can legitimately contain characters
    # (checkmarks, etc.) that the default Windows console codepage can't
    # encode -- replace rather than crash the agent over a log line.
    line = f"[living-doc-agent] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(line.encode(enc, errors="replace").decode(enc))


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {
        "session_id": None, "document_id": None, "durable_document_id": None,
        "owned_chunk_ids": None, "last_source_hash": None, "run_history": [],
    }


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def record_run(state: dict, action: str, **detail) -> None:
    state["run_history"].append(
        {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "action": action, **detail}
    )


def locate_owned_section(html: str) -> list[str] | None:
    """The 'search' step: locate the owned section -- heading plus every
    chunk under it until the next heading -- by its heading text."""
    return find_section_chunk_ids(html, OWNED_SECTION_HEADING)


def bootstrap_document(client: SuperDocsClient, state: dict, first_data: dict) -> None:
    """First-ever run: create the standing document in one shot, with the
    human sections and the owned section both present from the start."""
    log("no existing document in state -- creating the standing document for the first time")
    session = client.init_session([])
    session_id = session["session_id"]

    instruction = (
        "Create a document titled \"Team Operations Dashboard\" with, in this exact order:\n"
        f"1. {HUMAN_SECTION_1}\n"
        f"2. {HUMAN_SECTION_2}\n"
        f"3. A level-2 heading exactly \"{OWNED_SECTION_HEADING}\", followed by "
        f"{render_section_instruction(first_data)}"
    )
    result = client.chat(session_id, instruction)
    log(f"create response: {result.get('response')}")

    docs = client.list_session_documents(session_id)["documents"]
    focused = next(d for d in docs if d["focused"])
    durable_id = focused["durable_document_id"]

    detail = client.get_document(durable_id, include_html=True)
    owned_ids = locate_owned_section(detail["html"])
    if not owned_ids:
        raise RuntimeError(
            "created the document but could not locate the owned section by its heading text -- "
            "refusing to proceed without a confirmed set of chunk_ids to scope future edits to"
        )

    state.update(
        session_id=session_id,
        document_id=focused["document_id"],
        durable_document_id=durable_id,
        owned_chunk_ids=owned_ids,
    )
    record_run(state, "created", document_id=durable_id, owned_chunk_ids=owned_ids)
    log(f"created document {durable_id}, owned section = {len(owned_ids)} chunk(s): {owned_ids}")


def run(source_path: Path, preview: bool, auto_approve: bool) -> int:
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        log("SUPERDOCS_API_KEY not set -- see .env.example")
        return 1
    base_url = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app")
    client = SuperDocsClient(api_key, base_url)

    data = json.loads(source_path.read_text())
    new_hash = source_hash(data)
    state = load_state()

    if state["durable_document_id"] is None:
        if preview:
            log("PREVIEW: no document exists yet -- first run always creates the document; "
                "nothing to preview against. Re-run without --preview to create it.")
            return 0
        bootstrap_document(client, state, data)
        state["last_source_hash"] = new_hash
        save_state(state)
        log("bootstrap complete. Re-run with a changed --source file to see an update cycle.")
        return 0

    # --- stopping rule: unchanged source is a hard no-op, zero API calls ---
    if new_hash == state["last_source_hash"]:
        log(f"source unchanged (hash {new_hash[:12]}...) -- nothing to do, no API call made")
        record_run(state, "noop", source_hash=new_hash)
        save_state(state)
        return 0

    prev = state["last_source_hash"]
    log(f"source changed: {(prev[:12] + '...') if prev else 'none'} -> {new_hash[:12]}...")

    session_id = state["session_id"]

    # Re-locate the owned section defensively (the 'search' step) rather
    # than trusting the remembered chunk_ids blindly.
    before = client.get_document(state["durable_document_id"], include_html=True)
    owned_ids = locate_owned_section(before["html"])
    if not owned_ids:
        log("FATAL: could not locate the owned section in the current document -- refusing to guess")
        record_run(state, "failed_to_locate_section", source_hash=new_hash)
        save_state(state)
        return 1
    if set(owned_ids) != set(state.get("owned_chunk_ids") or []):
        log(f"owned section chunk set changed since last run (was {state.get('owned_chunk_ids')}, "
            f"now {owned_ids}) -- using the freshly located one")
    state["owned_chunk_ids"] = owned_ids
    before_snapshot = chunk_map_excluding(before["html"], owned_ids)

    instruction = (
        f"In the section headed exactly \"{OWNED_SECTION_HEADING}\", replace the existing table "
        f"ENTIRELY with a new table matching the following description -- do not insert an "
        f"additional table or paragraph alongside the old one, replace it in place so there is "
        f"exactly one table in this section afterward. Do not modify any other heading, "
        f"paragraph, or section anywhere else in the document:\n\n{render_section_instruction(data)}"
    )

    if preview:
        log("PREVIEW MODE (no-spend): the following would be sent, but no chat call is made:")
        print("-" * 70)
        print(instruction)
        print("-" * 70)
        record_run(state, "preview", source_hash=new_hash)
        save_state(state)
        log("preview complete -- 0 operations spent (verify with whoami)")
        return 0

    job = client.chat_async(session_id, instruction, approval_mode="ask_every_time")
    job_id = job["job_id"]
    log(f"submitted job {job_id}, polling...")

    status = None
    for _ in range(30):
        time.sleep(3)
        job = client.get_job(job_id)
        status = job["status"]
        if status in ("awaiting_approval", "completed", "failed"):
            break
    else:
        log(f"job did not reach a terminal state in time (last status: {status})")
        return 1

    if status == "failed":
        log(f"job failed: {job.get('error')}")
        record_run(state, "failed", source_hash=new_hash, error=job.get("error"))
        save_state(state)
        return 1

    if status == "awaiting_approval":
        pending = job["metadata"]["pending_changes"]
        owned_set = set(owned_ids)
        out_of_scope = [c for c in pending if c["chunk_id"] not in owned_set]
        if out_of_scope:
            log(f"BOUNDARY VIOLATION PREVENTED: {len(out_of_scope)} proposed change(s) target a "
                f"chunk outside the owned section {owned_ids}. Rejecting all changes in this batch.")
            client.reject_changes(
                session_id, job_id, [c["change_id"] for c in pending],
                feedback="Rejected: change touched a section outside this agent's ownership boundary.",
            )
            record_run(state, "rejected_boundary_violation", source_hash=new_hash,
                       offending_chunks=[c["chunk_id"] for c in out_of_scope])
            save_state(state)
            return 1

        change_ids = [c["change_id"] for c in pending]
        if not auto_approve:
            print("-" * 70)
            for c in pending:
                print(f"Proposed change to chunk {c['chunk_id']}:")
                print(f"  {c.get('ai_explanation', '')}")
            print("-" * 70)
            answer = input("Approve this change? [y/N] ").strip().lower()
            if answer != "y":
                client.reject_changes(session_id, job_id, change_ids, feedback="Rejected by human reviewer.")
                log("rejected by human reviewer")
                record_run(state, "rejected_by_human", source_hash=new_hash)
                save_state(state)
                return 0

        client.approve_changes(session_id, job_id, change_ids)
        log(f"approved {len(change_ids)} change(s), all confirmed scoped to the owned section")

        for _ in range(20):
            job = client.get_job(job_id)
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(2)

    if job["status"] != "completed":
        log(f"job ended in status {job['status']} after approval: {job.get('error')}")
        return 1

    # --- post-hoc boundary proof: independently re-fetch and hash-compare ---
    after = client.get_document(state["durable_document_id"], include_html=True)
    after_snapshot = chunk_map_excluding(after["html"], owned_ids)

    if before_snapshot != after_snapshot:
        # Real bug, found by hitting it: comparing only pre-existing keys
        # missed a chunk that got ADDED outside the owned section (the
        # insert-instead-of-replace failure mode this build's instruction
        # wording now prevents, but the check itself must catch it
        # independently either way -- that's the whole point of a post-hoc
        # check instead of trusting the pre-approval scope alone).
        added = sorted(set(after_snapshot) - set(before_snapshot))
        removed = sorted(set(before_snapshot) - set(after_snapshot))
        changed = sorted(k for k in before_snapshot.keys() & after_snapshot.keys() if before_snapshot[k] != after_snapshot[k])
        log(f"BOUNDARY VIOLATION DETECTED AFTER THE FACT outside the owned section: "
            f"added={added} removed={removed} changed={changed}. Treated as a hard failure.")
        record_run(state, "boundary_violation_detected_posthoc", source_hash=new_hash,
                   added=added, removed=removed, changed=changed)
        save_state(state)
        return 1

    log(f"boundary check passed: all {len(before_snapshot)} chunks outside the owned section "
        f"are byte-identical before/after")
    state["last_source_hash"] = new_hash
    record_run(state, "updated", source_hash=new_hash, owned_chunk_ids=owned_ids, boundary_verified=True)
    save_state(state)
    log("update complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--preview", action="store_true",
                         help="no-spend: show what would change, make no API calls that cost operations")
    parser.add_argument("--auto-approve", action="store_true",
                         help="skip the interactive human prompt (still logged, still boundary-checked)")
    args = parser.parse_args()

    try:
        return run(args.source, args.preview, args.auto_approve)
    except SuperDocsError as e:
        log(f"API error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
