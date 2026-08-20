"""Command line for the linter.

    stylefix lint  PAGE.md  --guide styleguides/house-product-style.md --apply
    stylefix batch docs/    --guide styleguides/plain-english-public.md --sample 5

Swapping the --guide argument is the only thing needed to change what the linter
enforces. No code path branches on which guide it is.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .batch import StoppingRule, lint_batch
from .client import SuperDocsClient, SuperDocsError
from .lint import lint_document

DOC_SUFFIXES = {".md", ".markdown", ".docx", ".html", ".htm", ".txt", ".rtf", ".pdf"}


def _events(verbose: bool):
    started = time.monotonic()

    def say(stage: str, message: str) -> None:
        if verbose:
            print(f"  [{time.monotonic() - started:6.1f}s] {stage:<7} {message}",
                  file=sys.stderr)

    return say


def _client(args) -> SuperDocsClient:
    key = os.environ.get("SUPERDOCS_API_KEY", "")
    if not key:
        raise SystemExit(
            "SUPERDOCS_API_KEY is not set.\n"
            "  PowerShell:  $env:SUPERDOCS_API_KEY = 'sk_...'\n"
            "  bash:        export SUPERDOCS_API_KEY=sk_..."
        )
    return SuperDocsClient(key, timeout=args.timeout, on_event=_events(args.verbose))


def _report_one(result) -> None:
    print(f"\n{result.document}  —  {result.guide}")
    if result.clean:
        # Careful with this wording. We know the model was given the guide and
        # proposed nothing; we do NOT know the document complies. Observed
        # 2026-08-19: the same page yielded three changes in one run and none in
        # the next. Claiming compliance here would be a bluff.
        print("  No changes proposed. This means the model found nothing to fix,")
        print("  not that the document is provably compliant with the guide.")
    for f in result.findings:
        mark = "fix " if f.applied else "skip"
        print(f"  {mark} [{f.rule_id}] {f.change.original[:60]!r}")
        print(f"       -> {f.change.replacement[:60]!r}")
        if not f.applied:
            print(f"       refused: {f.verdict.reason}")
        elif f.change.note:
            print(f"       {f.change.note}")
    print(f"\n  {len(result.applied)} applied, {len(result.dropped)} refused, "
          f"{result.operations} operation(s), {result.seconds:.1f}s")
    for note in result.notes:
        print(f"  note: {note}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stylefix",
        description="Style-guide linter that fixes in place, built on SuperDocs.",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--verbose", "-v", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--verbose", "-v", action="store_true")
    common.add_argument("--timeout", type=float, default=120.0)

    one = sub.add_parser("lint", help="lint a single page", parents=[common])
    one.add_argument("document", type=Path)
    one.add_argument("--guide", type=Path, required=True)
    one.add_argument("--apply", action="store_true",
                     help="apply the fixes the guard clears (default: report only)")
    one.add_argument("--export", default=None, metavar="FORMAT",
                     help="export after applying, e.g. docx or pdf")
    one.add_argument("--out", default=None, type=Path, metavar="PATH",
                     help="write the exported file here")

    many = sub.add_parser("batch", help="lint a docs set and report the profile",
                          parents=[common])
    many.add_argument("directory", type=Path)
    many.add_argument("--guide", type=Path, required=True)
    many.add_argument("--sample", type=int, default=None,
                      help="lint only N documents, chosen deterministically")
    many.add_argument("--max-ops", type=int, default=50,
                      help="stop once this many operations are spent (default 50)")
    many.add_argument("--apply", action="store_true")

    args = parser.parse_args(argv)
    session = f"stylefix-{int(time.time())}"

    try:
        client = _client(args)
        if args.command == "lint":
            result = lint_document(client, args.document, args.guide, session,
                                   apply=args.apply, export_format=args.export,
                                   export_to=args.out, on_event=_events(args.verbose))
            _report_one(result)
            return 0

        docs = [p for p in sorted(args.directory.rglob("*"))
                if p.is_file() and p.suffix.lower() in DOC_SUFFIXES]
        if not docs:
            raise SystemExit(f"no documents under {args.directory}")
        report = lint_batch(client, docs, args.guide, session, apply=args.apply,
                            stopping=StoppingRule(max_operations=args.max_ops),
                            sample_size=args.sample, on_event=_events(args.verbose))
        print(report.render())
        return 0
    except SuperDocsError as exc:
        print(f"\nSuperDocs API error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
