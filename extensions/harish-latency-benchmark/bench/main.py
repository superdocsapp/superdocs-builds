"""
CLI entrypoint.

    python -m bench.main                  # small-sample mode (default), cheap, safe
    python -m bench.main --debug-single    # ONE cycle only, full diagnostics, cheapest
    python -m bench.main --full --yes      # full run, skips confirmation
    python -m bench.main --full            # full run, prints cap, asks first

Reads SUPERDOCS_API_KEY from the environment (or a .env file via
python-dotenv). Never hardcode a key here or pass it on the command line
where it could land in shell history -- see README.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .runner import (run_benchmark, estimate_full_run_ops, FULL_SIZES, FULL_CONCURRENCY,
                      FULL_REPEATS, run_one_cycle)
from .report import build_report
from .client import SuperDocsClient


def verify_key(api_key: str) -> bool:
    """Free check (GET /v1/sessions, non-billable) before spending anything."""
    with SuperDocsClient(api_key) as client:
        r = client.whoami_sessions()
    if r.status_code != 200:
        print(f"Key verification failed: HTTP {r.status_code} -- {r.body}", file=sys.stderr)
        return False
    print("API key verified (0 operations consumed).")
    return True


def main():
    parser = argparse.ArgumentParser(description="SuperDocs latency/throughput benchmark")
    parser.add_argument("--full", action="store_true",
                         help="Run the full matrix (all sizes x concurrency x repeats). "
                              "Default is small-sample mode.")
    parser.add_argument("--yes", action="store_true",
                         help="Skip the spend-cap confirmation prompt for --full runs.")
    parser.add_argument("--out", default="bench_report.json",
                         help="Path to write the raw JSON report.")
    parser.add_argument("--sizing-guide-out", default="SIZING_GUIDE.md",
                         help="Path to write the derived sizing guide.")
    parser.add_argument("--debug-single", action="store_true",
                         help="Run exactly one cycle (small doc, concurrency=1) with full "
                              "diagnostic logging, then exit.")
    args = parser.parse_args()

    api_key = os.getenv("SUPERDOCS_API_KEY")
    if not api_key:
        print("SUPERDOCS_API_KEY not set. Copy .env.example to .env and fill it in, "
              "or export it in your shell.", file=sys.stderr)
        sys.exit(1)

    if not verify_key(api_key):
        sys.exit(1)

    if args.debug_single:
        print("Running a single debug cycle (small doc, concurrency=1)...")
        result = run_one_cycle(api_key, "small", 1)
        if result.fatal_error:
            print(f"\nFATAL: {result.fatal_error}")
            sys.exit(1)
        print("\nPhase results:")
        for p in result.phases:
            print(f"  {p.phase}: status={p.status_code} latency={p.latency_s:.2f}s "
                  f"rate_limited={p.rate_limited} error={p.error}")
        sys.exit(0)

    small_sample = not args.full
    if not small_sample:
        cap = estimate_full_run_ops()
        print(f"\nFull run estimate: {len(FULL_SIZES)} sizes x {len(FULL_CONCURRENCY)} "
              f"concurrency levels x {FULL_REPEATS} repeats.")
        print(f"Estimated operation spend cap for this run: ~{cap} operations "
              f"(1 billable edit per cycle; upload and export are non-billable).")
        if not args.yes:
            resp = input("Proceed with full run? [y/N] ").strip().lower()
            if resp != "y":
                print("Aborted. Re-run with --small-sample (default) or confirm with --yes.")
                sys.exit(0)

    print(f"\nRunning benchmark ({'small-sample' if small_sample else 'FULL'} mode)...")
    all_results = run_benchmark(api_key, small_sample=small_sample)
    report = build_report(all_results)

    serializable = {
        "cells": [
            {
                "tier": tier, "concurrency": conc,
                "phases": {p: vars(s) for p, s in report["stats_by_cell"][(tier, conc)].items()},
                "dispatch_check": report["dispatch_by_cell"][(tier, conc)],
                "fatal_errors": report["fatal_by_cell"][(tier, conc)],
            }
            for tier, conc in report["cells"]
        ]
    }
    with open(args.out, "w") as f:
        json.dump(serializable, f, indent=2)
    with open(args.sizing_guide_out, "w") as f:
        f.write(report["sizing_guide"])

    print(f"\nRaw stats written to {args.out}")
    print(f"Sizing guide written to {args.sizing_guide_out}")
    print("\n" + report["sizing_guide"])


if __name__ == "__main__":
    main()
