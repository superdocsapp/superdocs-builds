"""Command line runner.

    python -m ro_normalizer.cli normalize sample-data/orders.json --limit 5
    python -m ro_normalizer.cli batch     sample-data/batch-100.json --limit 100
    python -m ro_normalizer.cli process   sample-data/orders.json --limit 1

`--limit` defaults to the small-sample size. Processing a hundred orders is
something you ask for, not something that happens because a flag was forgotten.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ro_normalizer.config import build_editor
from ro_normalizer.superdocs.client import SuperDocsError
from ro_normalizer.services.batch import format_summary, load_orders, run_batch
from ro_normalizer.services.pipeline import process_order

DEFAULT_LIMIT = 5


def _print_order(result) -> None:
    print(f"\n{'─' * 72}\n{result.repair_order_id}   confidence: {result.confidence.value.upper()}")
    print(f"{'─' * 72}")
    print(result.narrative)

    if result.dtc_codes:
        print(f"\nDTC: {', '.join(result.dtc_codes)}")
    if result.measurements:
        print(f"Measurements: {', '.join(result.measurements)}")
    if result.missing_elements:
        print(f"Missing: {', '.join(e.value for e in result.missing_elements)}")

    print("Why: " + "; ".join(result.confidence_reasons))

    for warning in result.warnings:
        print(f"  ! {warning.code}: {warning.message}")
        for span in warning.evidence[:2]:
            print(f"      {span.text!r}")


def cmd_normalize(args: argparse.Namespace) -> int:
    orders = load_orders(args.path)
    result = run_batch(orders, max_orders=args.limit)
    for produced in result.results:
        _print_order(produced)
    print(f"\n{'═' * 72}")
    print(format_summary(result.summary))
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    orders = load_orders(args.path)
    result = run_batch(orders, max_orders=args.limit)

    print(format_summary(result.summary))
    if result.failures:
        print(f"\nFailures ({len(result.failures)}):")
        for order_id, message in result.failures:
            print(f"  {order_id}: {message}")
    if result.aborted:
        print("\nBatch aborted: too many failures.")

    if args.out:
        payload = [json.loads(r.model_dump_json()) for r in result.results]
        Path(args.out).write_text(json.dumps(payload, indent=1) + "\n")
        print(f"\nWrote {len(payload)} records to {args.out}")
    return 1 if result.aborted else 0


MAX_CONSECUTIVE_FAILURES = 3
"""A run failing this many times in a row is failing systematically.

The assignment is explicit that a loop with no stopping rule is a day-one
mistake. Operations cost money; proving the API is down twelve times over does
not make it more down.
"""


def cmd_process(args: argparse.Namespace) -> int:
    """The four-call flow, against the mock editor or the real API.

    Every order is processed exactly once. An earlier version re-ran the first
    order to print its document, which against the live API would have spent a
    second set of operations to show something it already had.
    """
    orders = load_orders(args.path)[: args.limit]
    editor = build_editor(args.backend)
    incomplete = 0
    consecutive_failures = 0

    for index, order in enumerate(orders):
        # A session holds one document, so the live editor needs a fresh one per
        # order. The mock is stateless enough to reuse, but there is no reason
        # for the two paths to differ.
        try:
            result = process_order(order, editor if index == 0 else build_editor(args.backend))
        except SuperDocsError as exc:
            # One unreachable order should not throw away the ones that worked.
            # But a run that is failing every time is failing systematically, and
            # continuing would spend operations proving it.
            incomplete += 1
            consecutive_failures += 1
            print(f"{order.repair_order_id}: FAILED — {exc}")
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(
                    f"\nStopping: {consecutive_failures} orders in a row failed. "
                    "Nothing is wrong with the remaining orders that another "
                    "attempt would fix."
                )
                break
            continue
        consecutive_failures = 0

        state = "auto-approved" if result.auto_approved else f"{len(result.rejected)} left for review"
        print(f"{result.order_id}: {result.approved} change(s) approved, {state}")
        for note in result.rejected:
            print(f"    not sent — {note}")
        if not result.complete:
            incomplete += 1
            if result.unwritten:
                print(f"    NOT WRITTEN: {', '.join(result.unwritten)}")
            if not result.source_intact:
                print("    NOT WRITTEN: the technician note is missing from the document")

        if index == 0:
            print(f"\n{'─' * 72}\nExported document for {result.order_id}\n{'─' * 72}")
            print(result.exported)
            print(f"{'─' * 72}\n")

    if incomplete:
        print(f"\n{incomplete} of {len(orders)} document(s) did not come out complete.")
    return 1 if incomplete else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ro_normalizer", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, handler, helptext in (
        ("normalize", cmd_normalize, "normalize orders and print each narrative"),
        ("batch", cmd_batch, "normalize orders and print only the summary"),
        ("process", cmd_process, "run the four-call document flow against the mock editor"),
    ):
        parser_sub = sub.add_parser(name, help=helptext)
        parser_sub.add_argument("path", help="JSON file of repair orders")
        parser_sub.add_argument(
            "--limit", type=int, default=DEFAULT_LIMIT,
            help=f"how many orders to process (default {DEFAULT_LIMIT})",
        )
        if name == "batch":
            parser_sub.add_argument("--out", help="write the full records to this JSON file")
        if name == "process":
            parser_sub.add_argument(
                "--backend", choices=("mock", "superdocs"), default=None,
                help="which editor to drive (default: EDITOR_BACKEND, or 'mock')",
            )
        parser_sub.set_defaults(handler=handler)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
