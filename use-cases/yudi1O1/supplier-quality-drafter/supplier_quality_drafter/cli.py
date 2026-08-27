"""CLI entrypoint.

    python -m supplier_quality_drafter check   examples/sample_input.yaml
    python -m supplier_quality_drafter draft   examples/sample_input.yaml --template templates/customer_template_a.html --out out/acme-fmea.docx
    python -m supplier_quality_drafter two-templates examples/sample_input.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Windows consoles default to a legacy codepage (cp1252) that can't encode
# characters like the emoji SuperDocs' AI sometimes returns in `response`
# text (e.g. U+2705 checkmark). Reconfigure stdout/stderr to UTF-8 so a
# perfectly valid AI response never crashes the CLI mid-run.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from .client import SuperDocsClient
from .io_yaml import load_draft_request
from .ledger import DEFAULT_LEDGER_PATH, RunLedger
from .validate import validate_request
from .workflow import approve_all, draft_document


def _print_findings(validation) -> None:
    if not validation.findings:
        print("No findings. Clean input.")
        return
    for f in validation.findings:
        tag = "BLOCKING" if f.severity == "blocking" else "warning "
        print(f"[{tag}] {f.location}: {f.message}")


def cmd_check(args: argparse.Namespace) -> int:
    req = load_draft_request(args.input)
    validation = validate_request(req)
    _print_findings(validation)
    if not validation.ok_to_draft:
        print(f"\n{len(validation.blocking)} blocking finding(s) — fix these before drafting.")
        return 1
    print("\nOK to draft.")
    return 0


def _interactive_approval(pending_changes: list[dict]) -> list[dict]:
    decisions = []
    for c in pending_changes:
        print("\n--- proposed change ---")
        print(f"operation: {c.get('operation')}")
        if c.get("old_html"):
            print(f"old: {c['old_html'][:300]}")
        if c.get("new_html"):
            print(f"new: {c['new_html'][:300]}")
        if c.get("ai_explanation"):
            print(f"why: {c['ai_explanation']}")
        ans = input("Approve this change? [Y/n] ").strip().lower()
        decisions.append({"change_id": c["change_id"], "approved": ans in ("", "y", "yes")})
    return decisions


def cmd_draft(args: argparse.Namespace) -> int:
    req = load_draft_request(args.input)
    validation = validate_request(req)
    _print_findings(validation)
    if not validation.ok_to_draft:
        print(f"\nRefusing to draft: {len(validation.blocking)} blocking finding(s).")
        return 1

    client = SuperDocsClient()
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)

    callback = approve_all if args.auto_approve else _interactive_approval

    result = draft_document(
        client,
        req,
        template_path=args.template,
        session_id=args.session_id,
        export_path=args.out,
        export_format=args.format,
        approval_callback=callback,
        model_tier=args.model_tier,
        ledger=RunLedger(args.ledger),
        force=args.force,
    )

    if result.skipped:
        print(f"\nSkipped (already drafted): {result.exported_path}")
    else:
        print(f"\nDrafted: {result.exported_path}")
    print(f"session_id={result.session_id} job_id={result.job_id}")
    if result.approvals:
        print(
            f"Review: {result.approvals.get('approved', 0)} change(s) approved, "
            f"{result.approvals.get('rejected', 0)} rejected."
        )
    if result.verification is not None:
        v = result.verification
        if not v.readable:
            print(f"Verified: not checked — {v.note}")
        else:
            print(f"Verified: {v.checked}/{v.checked} expected fact(s) present in the exported file.")
    if result.attempts > 1:
        print(f"Attempts: {result.attempts} (a cold session produced no changes on the first try).")
    if result.usage_summary:
        print(f"Cost: {result.usage_summary}")
    if result.ai_response:
        print(f"AI: {result.ai_response}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="supplier_quality_drafter")
    sub = p.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="Validate a YAML input file without calling the API.")
    p_check.add_argument("input")
    p_check.set_defaults(func=cmd_check)

    p_draft = sub.add_parser("draft", help="Draft a document on SuperDocs from a YAML input file.")
    p_draft.add_argument("input")
    p_draft.add_argument("--template", required=True, help="Path to the customer's template file (.docx/.html/...).")
    p_draft.add_argument("--session-id", required=True)
    p_draft.add_argument("--out", required=True, help="Output file path.")
    p_draft.add_argument("--format", default="docx", choices=["docx", "pdf", "html", "markdown", "txt"])
    p_draft.add_argument("--model-tier", default=None, choices=[None, "turbo", "core", "pro", "max"])
    p_draft.add_argument("--auto-approve", action="store_true", help="Approve every proposed change without prompting (CI/demo use).")
    p_draft.add_argument(
        "--ledger", default=DEFAULT_LEDGER_PATH,
        help="Path to the idempotency ledger that prevents paying twice for an identical draft.",
    )
    p_draft.add_argument(
        "--force", action="store_true",
        help="Redraft even if an identical draft already completed (spends another operation).",
    )
    p_draft.set_defaults(func=cmd_draft)

    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
