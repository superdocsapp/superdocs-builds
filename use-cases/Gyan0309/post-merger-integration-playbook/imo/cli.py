"""The driver: deal spec in, reviewed document set out.

    python -m imo.cli deals/northstar.yaml --out build/

Stages, in order:

    1. load      the deal spec, validated
    2. detect    cross-workstream conflicts, deterministically, no model
    3. render    the document set from the spec, deterministically, no model
    4. upload    each document into its own SuperDocs session
    5. flag      each conflict into every document that has a stake in it
    6. review    per-item approval of the proposed changes
    7. export    the finished set

Stages 1–3 need no API key and no network, which means the whole detection and
rendering half of this build is testable offline. Only 4–7 touch SuperDocs.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

from imo.conflicts import detect, summarise
from imo.deal import DealSpecError, load_deal
from imo.documents import flag_conflicts_in_document, plan_fan_out, render_all
from imo.superdocs import SuperDocsClient, SuperDocsError

logger = logging.getLogger("imo")


def configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a post-merger integration document set.")
    parser.add_argument("deal", type=Path, help="path to a deal YAML spec")
    parser.add_argument("--out", type=Path, default=Path("build"), help="output directory")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="render and detect only; do not contact SuperDocs. Needs no API key.",
    )
    parser.add_argument(
        "--session-prefix",
        default=None,
        help="prefix for SuperDocs session ids (default: a fresh random one)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    configure_logging(args.verbose)

    # -- 1. load -----------------------------------------------------------
    try:
        deal = load_deal(args.deal)
    except DealSpecError as exc:
        print(f"deal spec is invalid: {exc}", file=sys.stderr)
        return 2

    print(f"\nProject {deal.code_name}: {deal.acquirer} acquires {deal.target}")
    print(f"  {len(deal.workstreams)} workstreams, close {deal.expected_close}")

    # -- 2. detect ---------------------------------------------------------
    conflicts = detect(deal)
    stats = summarise(conflicts)
    print(f"\nConflicts detected: {stats['total']} "
          f"({stats['high']} high, {stats['medium']} medium) "
          f"across {stats['workstreams_affected']} workstreams")
    for conflict in conflicts:
        print(f"  [{conflict.severity}] {conflict.summary}")
        print(f"      surfaced in: {', '.join(conflict.affects)}")

    # -- 3. render ---------------------------------------------------------
    args.out.mkdir(parents=True, exist_ok=True)
    documents = render_all(deal)
    for document in documents:
        document.write(args.out)
    print(f"\nRendered {len(documents)} documents into {args.out}/")

    fan_out = plan_fan_out(deal, conflicts)
    if fan_out:
        print("\nEach conflict lands in every document with a stake in it:")
        for key, items in sorted(fan_out.items()):
            print(f"  {key:<26} {len(items)} conflict(s)")

    if args.offline:
        print("\n--offline: stopping before SuperDocs. Documents and detection are done.")
        return 0

    # -- 4..7 --------------------------------------------------------------
    try:
        client = SuperDocsClient()
    except SuperDocsError as exc:
        print(f"\n{exc}", file=sys.stderr)
        print("Run with --offline to render and detect without an API key.", file=sys.stderr)
        return 3

    before = client.ops_remaining()
    prefix = args.session_prefix or f"{deal.code_name.lower()}-{uuid.uuid4().hex[:6]}"
    by_key = {d.key: d for d in documents}
    sessions: dict[str, str] = {}

    print(f"\nUploading to SuperDocs (session prefix {prefix})")
    for document in documents:
        session_id = f"{prefix}-{document.key}"
        client.upload(args.out / document.filename, session_id=session_id)
        sessions[document.key] = session_id
        print(f"  {document.filename}")

    print("\nFlagging conflicts through SuperDocs")
    outcomes = []
    for key, items in sorted(fan_out.items()):
        document = by_key.get(key)
        if document is None:
            continue
        audience = key.removeprefix("workstream-")
        outcomes += flag_conflicts_in_document(
            client,
            session_id=sessions[key],
            document_key=key,
            audience=audience,
            conflicts=items,
        )

    landed = sum(1 for o in outcomes if o.landed)
    print(f"  {landed}/{len(outcomes)} conflict flags landed")

    print("\nExporting")
    exports = args.out / "exported"
    exports.mkdir(exist_ok=True)
    for document in documents:
        client.export(
            sessions[document.key],
            fmt="markdown",
            destination=exports / document.filename,
        )
    print(f"  {len(documents)} documents into {exports}/")

    after = client.ops_remaining()
    if before is not None and after is not None:
        print(f"\nOperations spent: {before - after}  ({after} remaining)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
