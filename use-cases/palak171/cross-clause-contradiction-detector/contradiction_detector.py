"""
Cross-clause contradiction detector, built on SuperDocs.

Touches all three surfaces named on the assigned build's card:
  - chat / search:  a read-only detection pass — ask SuperDocs' AI to find
                     genuine contradictions between clauses, cited by number,
                     without touching the document.
  - Review (HITL):  a second pass proposes an edit per confirmed contradiction;
                     each proposed edit is approved or rejected individually
                     through /v1/chat/{session_id}/approve, never all-or-nothing.

Precision over coverage, per the card's "what strong looks like": the
detection prompt is written to explicitly exclude ordinary tension between
clauses on different subjects, and the resolve step only ever acts on
contradictions the detection pass actually named — it never invents new ones
to "find more."

Usage:
    python contradiction_detector.py run contract.docx --export reviewed.docx
    python contradiction_detector.py detect contract.docx
    python contradiction_detector.py resolve SESSION_ID --export reviewed.docx
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

from dotenv import load_dotenv

from superdocs_client import JobTimeout, SuperDocsClient, SuperDocsError

DETECTION_PROMPT = """\
Review this contract for cross-clause contradictions only. A contradiction is \
two clauses that cannot both be true or both be followed at once — for \
example, conflicting numeric terms (one clause says 30 days, another says 45 \
days for the same obligation), conflicting obligations, or mutually exclusive \
requirements.

Do NOT flag: clauses that merely address related but different subjects, \
clauses that add detail to each other without conflicting, or ordinary legal \
boilerplate tension. A false positive here is worse than a missed one —
precision is what is being measured, not the length of the list.

For every genuine contradiction you find, report it as:
N. Clause <X> vs Clause <Y>: <one-sentence description of exactly what \
conflicts, quoting the conflicting terms from each clause>

If you find no genuine contradictions, say so plainly: "No cross-clause \
contradictions found." Do not edit the document in this pass — analysis only.
"""

RESOLVE_PROMPT = """\
You previously identified cross-clause contradictions in this document. For \
each one you named, propose a single edit that resolves it: align the earlier \
or more general clause to match the later, more specific clause (the one that \
supersedes, per its own "notwithstanding"/"supersedes" language if present; \
otherwise the more recently-numbered clause). Propose one edit per \
contradiction, not a rewrite of anything else. In each edit's explanation, \
name both clause numbers and state which value you kept and why.
"""


def new_session_id() -> str:
    return f"contradiction-detector-{uuid.uuid4().hex[:8]}"


def cmd_detect(client: SuperDocsClient, contract_path: str, session_id: str,
               model_tier: str | None, thinking_depth: str | None) -> str:
    print(f"Uploading {contract_path} into session {session_id} ...")
    client.upload_document(contract_path, session_id)

    print("Running detection pass (chat/search surface, no edits made) ...")
    result = client.chat(DETECTION_PROMPT, session_id, model_tier=model_tier,
                          thinking_depth=thinking_depth)
    print("\n--- Contradiction report ---")
    print(result["response"])
    print("---\n")
    usage = result.get("usage", {})
    if usage:
        print(f"Operations used this call: {usage.get('ops_charged', '?')} "
              f"(monthly remaining: {usage.get('monthly_remaining', '?')})")
    return session_id


def cmd_resolve(client: SuperDocsClient, session_id: str, auto_approve: bool, auto_deny: bool,
                 export_path: str | None, export_format: str) -> None:
    print("Requesting resolution edits (Review/HITL surface) ...")
    started = client.start_edit(RESOLVE_PROMPT, session_id)
    job_id = started["job_id"]

    while True:
        try:
            job = client.wait_for_job(job_id)
        except JobTimeout as exc:
            print(f"Timed out waiting for SuperDocs: {exc}", file=sys.stderr)
            sys.exit(1)

        if job["status"] == "failed":
            print(f"SuperDocs job failed: {job.get('error')}", file=sys.stderr)
            sys.exit(1)

        if job["status"] == "awaiting_approval":
            changes = client.pending_changes(job)
            print(f"\n{len(changes)} proposed edit(s) awaiting review:\n")
            decisions = []
            for change in changes:
                print(f"  [{change.change_id}] {change.operation}")
                print(f"    Why: {change.ai_explanation}")
                print(f"    Old: {change.old_html[:200]}")
                print(f"    New: {change.new_html[:200]}")

                if auto_approve:
                    approved, feedback = True, None
                elif auto_deny:
                    approved, feedback = False, "auto-denied (dry run)"
                else:
                    answer = input("    Approve this edit? [y/N/reason to deny]: ").strip()
                    approved = answer.lower() == "y"
                    feedback = None if approved else (answer if answer and answer.lower() != "n" else None)

                decisions.append((change.change_id, approved, feedback))
                print(f"    -> {'APPROVED' if approved else 'REJECTED'}\n")

            client.approve_changes(session_id, job_id, decisions)
            continue  # poll again; the job resumes after approval

        if job["status"] == "completed":
            print("Done:", job.get("result", {}).get("response", "(no summary returned)"))
            break

    if export_path:
        print(f"Exporting to {export_path} ...")
        result = client.export_document(session_id, format=export_format)
        with open(export_path, "wb") as f:
            f.write(result.content)
        if result.warnings:
            print(f"Export completed with {len(result.warnings)} warning(s): {result.warnings}")
        print(f"Wrote {len(result.content)} bytes to {export_path}")


def main():
    # SuperDocs' AI responses can contain emoji/non-ASCII characters; Windows
    # consoles default to a legacy codepage (cp1252) that can't print them.
    # Bug found live against the real API on 2026-08-08 — see PROGRESS.md.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    load_dotenv()
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        print("Set SUPERDOCS_API_KEY (in your environment or a .env file) before running this.",
              file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_detect = sub.add_parser("detect", help="Read-only contradiction report, no edits made.")
    p_detect.add_argument("contract_path")
    p_detect.add_argument("--session-id", default=None)
    p_detect.add_argument("--model-tier", default=None, choices=["core", "turbo", "pro", "max"])
    p_detect.add_argument("--thinking-depth", default=None, choices=["fast", "balanced", "deep"])

    p_resolve = sub.add_parser("resolve", help="Propose and review edits for a session that's already run 'detect'.")
    p_resolve.add_argument("session_id")
    p_resolve.add_argument("--auto-approve", action="store_true", help="Approve every proposed edit without asking.")
    p_resolve.add_argument("--auto-deny", action="store_true", help="Reject every proposed edit (dry run).")
    p_resolve.add_argument("--export", dest="export_path", default=None)
    p_resolve.add_argument("--format", dest="export_format", default="docx",
                            choices=["docx", "pdf", "html", "markdown", "txt"])

    p_run = sub.add_parser("run", help="detect + resolve + optional export, in one go.")
    p_run.add_argument("contract_path")
    p_run.add_argument("--session-id", default=None)
    p_run.add_argument("--auto-approve", action="store_true")
    p_run.add_argument("--auto-deny", action="store_true")
    p_run.add_argument("--export", dest="export_path", default=None)
    p_run.add_argument("--format", dest="export_format", default="docx",
                        choices=["docx", "pdf", "html", "markdown", "txt"])
    p_run.add_argument("--model-tier", default=None, choices=["core", "turbo", "pro", "max"])
    p_run.add_argument("--thinking-depth", default=None, choices=["fast", "balanced", "deep"])

    args = parser.parse_args()

    with SuperDocsClient(api_key) as client:
        try:
            if args.command == "detect":
                session_id = args.session_id or new_session_id()
                cmd_detect(client, args.contract_path, session_id, args.model_tier, args.thinking_depth)
                print(f"Session id (pass to 'resolve'): {session_id}")

            elif args.command == "resolve":
                cmd_resolve(client, args.session_id, args.auto_approve, args.auto_deny,
                            args.export_path, args.export_format)

            elif args.command == "run":
                session_id = args.session_id or new_session_id()
                cmd_detect(client, args.contract_path, session_id, args.model_tier, args.thinking_depth)
                cmd_resolve(client, session_id, args.auto_approve, args.auto_deny,
                            args.export_path, args.export_format)

        except SuperDocsError as exc:
            print(f"SuperDocs API error: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
