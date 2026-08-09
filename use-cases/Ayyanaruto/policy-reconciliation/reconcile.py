#!/usr/bin/env python3
"""CLI: reconcile two HR policy estates, then apply human decisions."""

from __future__ import annotations

import argparse
import sys

import pipeline
from superdocs_client import QuotaExhausted, SuperDocsError, load_dotenv


def main(argv=None):
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Reconcile two HR / employee-handbook estates via SuperDocs."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("reconcile", help="Upload, match, detect conflicts, draft merges")
    rec.add_argument("--estate-a", required=True, help="Folder of Company A .docx policies")
    rec.add_argument("--estate-b", required=True, help="Folder of Company B .docx policies")
    rec.add_argument("--output", required=True, help="Output folder, e.g. outputs/run_1")
    rec.add_argument("--dry-run", action="store_true", help="No SuperDocs calls; inventory only")
    rec.add_argument("--limit", type=int, default=None, help="Cap documents per estate")

    app = sub.add_parser("apply", help="Apply decisions.yaml (HITL approve / copy-through / export)")
    app.add_argument("--decisions", required=True, help="Path to decisions.yaml from a reconcile run")

    args = parser.parse_args(argv)
    try:
        if args.command == "reconcile":
            pipeline.run_reconcile(
                estate_a=args.estate_a,
                estate_b=args.estate_b,
                output=args.output,
                dry_run=args.dry_run,
                limit=args.limit,
            )
        elif args.command == "apply":
            pipeline.run_apply(args.decisions)
    except QuotaExhausted as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except SuperDocsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
