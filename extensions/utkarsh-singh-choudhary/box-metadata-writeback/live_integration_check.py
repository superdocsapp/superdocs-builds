#!/usr/bin/env python3
"""Run this LOCALLY, on your machine, with real credentials in your
environment. It never reads a key from an argument or a chat message --
only from os.environ -- and it never prints the key value anywhere in
its output. Paste the printed report back for debugging; the key never
needs to leave your machine.

Usage:
    export SUPERDOCS_API_KEY=sk_...          # required
    # Optional: also exercise the real Box client instead of the fake one
    export BOX_CLIENT_ID=...
    export BOX_CLIENT_SECRET=...
    export BOX_ENTERPRISE_ID=...
    export BOX_JWT_PRIVATE_KEY=...            # or BOX_JWT_PRIVATE_KEY_PATH
    python live_integration_check.py

What it does:
    1. Builds a RealSuperDocsClient from env (fails loudly with a clear
       message if SUPERDOCS_API_KEY isn't set -- never silently falls
       back to the fake).
    2. Builds either a RealBoxClient (if BOX_* vars are present) or a
       FakeBoxClient (if not) -- so you can test "does SuperDocs actually
       work" independently of having live Box credentials on hand.
    3. Seeds one realistic contract document (in-memory, or in a real Box
       folder if using RealBoxClient -- see --box-folder-id) and runs it
       through the full pipeline: classify -> extract -> generate
       companion -> normalize -> commit metadata.
    4. Prints a stage-by-stage pass/fail report: status, latency, retry
       counts, and (for failures) the real error message and HTTP status
       code SuperDocs returned -- exactly what's needed to debug, with
       nothing secret in it.
    5. Exits non-zero if any stage failed, so this is CI-usable too.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

# Make sure we're running from the repo root regardless of caller's cwd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CONTRACT_TEXT = b"""SERVICES AGREEMENT

This Services Agreement ("Agreement") is entered into as of January 15, 2026,
by and between Acme Logistics Inc ("Counterparty") and the Company.

Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Contract Value: $84,000.00

1. SERVICES. Counterparty shall provide logistics management services...
2. TERM. This Agreement shall remain in effect from the Effective Date
   through the Expiration Date unless earlier terminated.
3. PAYMENT. Company shall pay Counterparty the Contract Value in
   quarterly installments.
"""


def _redact_check(value: str) -> None:
    """Defensive check: makes sure nothing that looks like the API key
    itself ever gets assembled into a print statement in this script."""
    key = os.environ.get("SUPERDOCS_API_KEY", "")
    if key and key in value:
        raise RuntimeError("refusing to print a string containing the API key")


def build_clients(args):
    from app.clients.real_superdocs_client import RealSuperDocsClient

    superdocs = RealSuperDocsClient.from_env()
    if superdocs is None:
        print("FATAL: SUPERDOCS_API_KEY is not set in the environment.")
        print("Run:  export SUPERDOCS_API_KEY=sk_your_key   (then re-run this script)")
        sys.exit(2)

    have_box_creds = all(
        os.environ.get(v) for v in ("BOX_CLIENT_ID", "BOX_CLIENT_SECRET", "BOX_ENTERPRISE_ID")
    )
    if have_box_creds:
        from app.clients.real_box_client import RealBoxClient

        box = RealBoxClient.from_env()
        if box is None:
            print("FATAL: BOX_* vars are partially set but RealBoxClient.from_env() returned None.")
            print("Check BOX_CLIENT_ID / BOX_CLIENT_SECRET / BOX_ENTERPRISE_ID / BOX_JWT_PRIVATE_KEY.")
            sys.exit(2)
        mode = "real Box + real SuperDocs"
    else:
        from app.clients.fake_box_client import FakeBoxClient

        box = FakeBoxClient()
        box.seed_file("live-check-1", "services_agreement.txt", CONTRACT_TEXT)
        mode = "fake Box (no BOX_* env vars found) + real SuperDocs"

    return box, superdocs, mode, have_box_creds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file-id",
        default="live-check-1",
        help="Box file_id to process. Required (and must already exist in "
        "your Box tenant) if BOX_* env vars are set; ignored otherwise, "
        "since a fake file is seeded automatically.",
    )
    args = parser.parse_args()

    from app.workflow.pipeline import BoxMetadataWritebackPipeline

    box, superdocs, mode, live_box = build_clients(args)
    file_id = args.file_id if live_box else "live-check-1"

    pipeline = BoxMetadataWritebackPipeline(box, superdocs)

    print("=" * 72)
    print("LIVE INTEGRATION CHECK")
    print(f"mode: {mode}")
    print(f"file_id: {file_id}")
    print("=" * 72)

    t0 = time.monotonic()
    try:
        report = pipeline.process(file_id)
    except Exception as e:
        _redact_check(str(e))
        print(f"\nFATAL: pipeline.process() raised before producing a report: {e!r}")
        print("This usually means auth failed (bad key) or the base URL is wrong.")
        sys.exit(1)
    total_wall = time.monotonic() - t0

    if report.skipped_reason:
        print(f"\nRun was SKIPPED: {report.skipped_reason}")
        sys.exit(0)

    print(f"\n{'STAGE':<22}{'STATUS':<10}{'LATENCY_MS':<12}{'OPS':<6}DETAIL")
    print("-" * 100)
    any_failed = False
    for s in report.stages:
        detail = s.detail[:80]
        _redact_check(detail)
        if s.status == "failed":
            any_failed = True
        print(f"{s.name:<22}{s.status:<10}{s.latency_ms:<12.1f}{s.operations:<6}{detail}")

    print("-" * 100)
    print(f"total_operations={report.total_operations}  total_latency_ms={report.total_latency_ms:.1f}"
          f"  wall_clock_s={total_wall:.1f}")

    if report.extracted:
        print("\nExtracted fields (from the real SuperDocs response):")
        for field_name in ("counterparty_name", "effective_date", "expiration_date", "contract_value"):
            value = getattr(report.extracted, field_name, None)
            conf = report.extracted.field_confidence.get(field_name)
            print(f"  {field_name:<20} = {value!r:<30} confidence={conf}")

    if report.queued_for_review:
        print(f"\nQueued for human review (below confidence threshold): {report.queued_for_review}")

    print(f"\nMetadata written to Box: {report.metadata_written}")

    unresolved_dlq = pipeline.dead_letter.list_unresolved(file_id=file_id)
    if unresolved_dlq:
        print(f"\nDead-letter entries created this run: {len(unresolved_dlq)}")
        for e in unresolved_dlq:
            print(f"  [{e.entry_id}] stage={e.stage} attempts={e.attempts} reason={e.reason[:100]}")

    print(f"\ncircuit_breaker.is_open = {pipeline.circuit_breaker.is_open}")

    if any_failed:
        print("\nRESULT: FAIL -- at least one stage failed. See table above.")
        sys.exit(1)
    print("\nRESULT: PASS -- all stages completed against the real SuperDocs API.")
    sys.exit(0)


if __name__ == "__main__":
    main()
