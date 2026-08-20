"""CLI entrypoint: `winloss <command>`.

    winloss debrief create --transcript PATH --deal-code C --quarter Q --segment S \\
        --outcome win|loss --customer-name NAME [--customer-alias A ...] \\
        [--force] [--auto-approve] [--dry-run]
    winloss debrief list [--quarter Q]
    winloss brief quarterly --quarter Q [--auto-approve] [--dry-run]
    winloss search --competitor X | --segment Y | --outcome win|loss
    winloss redact-check FILE

Every command that would call the network supports --dry-run, which prints the
exact prompt/session/export plan and makes zero HTTP requests -- see
architecture.md §11.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .client import SuperDocsClient
from .config import MissingAPIKeyError, load_settings, require_api_key
from .debrief import AttachmentProcessingFailed, SkippedAlreadyIndexed, create_debrief, preview_debrief_call
from .index import Index
from .redaction import extract_text_from_file, scan_for_leaks
from .review import auto_approve_all, interactive_prompt
from .synthesis import create_quarterly_brief, preview_synthesis_call
from .templates import DebriefInput

DEFAULT_INDEX_PATH = Path("data/index/debriefs.json")
DEFAULT_DEBRIEF_OUTPUT_DIR = Path("outputs/debriefs")
DEFAULT_BRIEF_OUTPUT_DIR = Path("outputs/briefs")


def _build_client() -> SuperDocsClient:
    settings = load_settings()
    api_key = require_api_key(settings)
    return SuperDocsClient(settings, api_key)


def cmd_debrief_create(args: argparse.Namespace) -> int:
    transcript_path = Path(args.transcript)
    if not transcript_path.exists():
        print(f"error: transcript not found: {transcript_path}", file=sys.stderr)
        return 2

    inp = DebriefInput(deal_code=args.deal_code, quarter=args.quarter, segment=args.segment, outcome=args.outcome)

    if args.dry_run:
        print(json.dumps(preview_debrief_call(inp, transcript_path), indent=2))
        return 0

    try:
        client = _build_client()
    except MissingAPIKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    index = Index(DEFAULT_INDEX_PATH)
    callback = auto_approve_all if args.auto_approve else interactive_prompt

    try:
        result = create_debrief(
            client,
            index,
            transcript_path=transcript_path,
            deal_code=args.deal_code,
            quarter=args.quarter,
            segment=args.segment,
            outcome=args.outcome,
            customer_name=args.customer_name,
            customer_aliases=args.customer_alias or [],
            output_dir=DEFAULT_DEBRIEF_OUTPUT_DIR,
            approval_callback=callback,
            force=args.force,
        )
    except SkippedAlreadyIndexed as e:
        print(f"skipped: {e}")
        return 0
    except AttachmentProcessingFailed as e:
        # The hard-stop safety check (see progress.md Entry 6) -- printed cleanly
        # here rather than as a raw traceback, since this is a real, expected
        # outcome (not a crash) whenever transcript attachment processing doesn't
        # genuinely complete. No operation was spent on a chat call for this run.
        print(f"error: {e}", file=sys.stderr)
        print(
            "No chat call was made and nothing was written or indexed. This is "
            "usually transient (a cold-start session, or a slow/rate-limited "
            "attachment processor) -- re-running the same command is often enough. "
            "If it repeats, check the file is readable, non-empty, and a plain "
            "text/txt transcript.",
            file=sys.stderr,
        )
        return 1

    print(f"Debrief written: {result.exported_path}")
    print(f"Operations used this run: {client.usage.ops_used}")
    if result.unverified_evidence:
        print(f"WARNING: {len(result.unverified_evidence)} evidence quote(s) could not be verified against the transcript:")
        for q in result.unverified_evidence:
            print(f"  - {q}")
    return 0


def cmd_debrief_list(args: argparse.Namespace) -> int:
    index = Index(DEFAULT_INDEX_PATH)
    records = index.for_quarter(args.quarter) if args.quarter else index.all()
    for r in records:
        print(f"{r.deal_code}\t{r.quarter}\t{r.segment}\t{r.outcome}\tcompetitors={r.competitors}")
    if not records:
        print("(no debriefs indexed)")
    return 0


def cmd_brief_quarterly(args: argparse.Namespace) -> int:
    settings = load_settings()
    index = Index(DEFAULT_INDEX_PATH)

    if args.dry_run:
        print(json.dumps(preview_synthesis_call(args.quarter, index, settings.small_sample_threshold), indent=2, default=str))
        return 0

    try:
        client = _build_client()
    except MissingAPIKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    callback = auto_approve_all if args.auto_approve else interactive_prompt

    try:
        result = create_quarterly_brief(
            client,
            index,
            quarter=args.quarter,
            output_dir=DEFAULT_BRIEF_OUTPUT_DIR,
            small_sample_threshold=settings.small_sample_threshold,
            approval_callback=callback,
        )
    except Exception as e:  # includes RedactionBlockedExport -- surfaced, not swallowed
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"Quarterly brief written: {result.exported_docx_path}")
    if result.exported_pdf_path:
        print(f"Also exported: {result.exported_pdf_path}")
    print(f"Debriefs synthesized: {result.debrief_count}")
    print(f"Operations used this run: {client.usage.ops_used}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    index = Index(DEFAULT_INDEX_PATH)
    if args.competitor:
        records = index.by_competitor(args.competitor)
    elif args.segment:
        records = index.by_segment(args.segment)
    elif args.outcome:
        records = index.by_outcome(args.outcome)
    else:
        records = index.all()
    for r in records:
        print(f"{r.deal_code}\t{r.quarter}\t{r.segment}\t{r.outcome}\tcompetitors={r.competitors}")
    if not records:
        print("(no matches)")
    return 0


def cmd_redact_check(args: argparse.Namespace) -> int:
    index = Index(DEFAULT_INDEX_PATH)
    try:
        text = extract_text_from_file(Path(args.file))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    result = scan_for_leaks(text, index.all_customer_terms())
    if result.ok:
        print("clean: no known customer identifiers found")
        return 0
    print(f"LEAK DETECTED: {result.leaked_terms}", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="winloss", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    debrief = sub.add_parser("debrief", help="Manage individual deal debriefs")
    debrief_sub = debrief.add_subparsers(dest="debrief_command", required=True)

    create = debrief_sub.add_parser("create", help="Draft a debrief from a transcript")
    create.add_argument("--transcript", required=True)
    create.add_argument("--deal-code", required=True)
    create.add_argument("--quarter", required=True, help="e.g. 2025Q4")
    create.add_argument("--segment", required=True)
    create.add_argument("--outcome", required=True, choices=["win", "loss"])
    create.add_argument("--customer-name", required=True)
    create.add_argument("--customer-alias", action="append", default=[])
    create.add_argument("--force", action="store_true")
    create.add_argument("--auto-approve", action="store_true")
    create.add_argument("--dry-run", action="store_true")
    create.set_defaults(func=cmd_debrief_create)

    listc = debrief_sub.add_parser("list", help="List indexed debriefs")
    listc.add_argument("--quarter")
    listc.set_defaults(func=cmd_debrief_list)

    brief = sub.add_parser("brief", help="Quarterly competitive brief")
    brief_sub = brief.add_subparsers(dest="brief_command", required=True)
    quarterly = brief_sub.add_parser("quarterly", help="Synthesize a quarter's debriefs")
    quarterly.add_argument("--quarter", required=True)
    quarterly.add_argument("--auto-approve", action="store_true")
    quarterly.add_argument("--dry-run", action="store_true")
    quarterly.set_defaults(func=cmd_brief_quarterly)

    search = sub.add_parser("search", help="Search the local debrief index")
    search.add_argument("--competitor")
    search.add_argument("--segment")
    search.add_argument("--outcome", choices=["win", "loss"])
    search.set_defaults(func=cmd_search)

    redact = sub.add_parser("redact-check", help="Scan a text/HTML file for known customer identifiers")
    redact.add_argument("file")
    redact.set_defaults(func=cmd_redact_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
