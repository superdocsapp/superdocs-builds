#!/usr/bin/env python3
"""
CLI entry point.

Examples:
  # Small-sample mode first, per the task brief's "budget your operations":
  python run_batch.py --limit 2

  # Full roster, second run (extends the same clients' documents further):
  python run_batch.py --advance --limit 2   # first make a 3rd assessment exist
  python run_batch.py

Environment:
  SUPERDOCS_API_KEY must be set (see .env.example).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.batch_runner import run_batch
from src.fixtures import make_synthetic_roster
from src.state_store import StateStore
from src.superdocs_client import SuperDocsClient

DEFAULT_STATE_PATH = "data/state.json"
DEFAULT_OUTPUT_DIR = "output"


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--roster-size", type=int, default=8, help="Number of synthetic clients to generate")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N clients (small-sample mode)")
    parser.add_argument("--state-path", default=DEFAULT_STATE_PATH)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    clients = make_synthetic_roster(n_clients=args.roster_size, seed=args.seed)
    state = StateStore(args.state_path)

    try:
        sd = SuperDocsClient()
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("Copy .env.example to .env and set SUPERDOCS_API_KEY.", file=sys.stderr)
        sys.exit(1)

    if not sd.verify_key():
        print("ERROR: SuperDocs API key did not verify against GET /v1/sessions.", file=sys.stderr)
        sys.exit(1)

    with sd:
        results = run_batch(clients, sd, state, Path(args.output_dir), limit=args.limit)

    ok = sum(1 for r in results if r.status in ("baseline_created", "report_appended"))
    skipped = sum(1 for r in results if r.status == "skipped_already_run")
    errors = sum(1 for r in results if r.status == "error")
    print(f"\nDone. {ok} processed, {skipped} skipped (idempotent), {errors} errors.")
    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
