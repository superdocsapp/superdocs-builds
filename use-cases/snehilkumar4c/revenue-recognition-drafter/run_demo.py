#!/usr/bin/env python3
"""Runs the revenue recognition drafter end to end on one of the bundled
fixture contracts.

Usage:
    python run_demo.py                                  # analyze + draft only
    python run_demo.py --contract saas                  # pick a fixture
    python run_demo.py --publish                         # also push to SuperDocs
    python run_demo.py --publish --auto-approve           # publish, auto-resolving
                                                            # HITL edits via
                                                            # code-level content
                                                            # verification

Requires ANTHROPIC_API_KEY always. SUPERDOCS_API_KEY is only required with
--publish.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from core.llm import LLMClient
from core.superdocs_client import SuperDocsClient
from drafter.runner import draft_memo, publish_memo_to_superdocs

FIXTURES = {
    "saas": "tests/fixtures/drafter/contract_saas_bundled.txt",
    "milestones": "tests/fixtures/drafter/contract_services_milestones.txt",
    "hardware": "tests/fixtures/drafter/contract_hardware_warranty.txt",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", choices=FIXTURES, default="hardware")
    parser.add_argument(
        "--publish", action="store_true", help="Also push the memo through SuperDocs (HITL)."
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="With --publish: auto-resolve proposed edits via content verification "
        "instead of returning control for manual review.",
    )
    parser.add_argument("--format", default="docx", help="Export format with --publish.")
    args = parser.parse_args()

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        print("ANTHROPIC_API_KEY is required. Copy .env.example to .env and fill it in.", file=sys.stderr)
        return 1

    contract_path = Path(__file__).parent / FIXTURES[args.contract]
    llm = LLMClient(api_key=anthropic_key)

    print(f"Drafting a revenue recognition memo from {contract_path.name}...\n")
    state = draft_memo(str(contract_path), llm)

    analysis = state["analysis"]
    print(f"Performance obligations found: {len(analysis['performance_obligations'])}")
    print(f"Price allocations found: {len(analysis['price_allocations'])}")
    print(f"Timing conclusions found: {len(analysis['timing_conclusions'])}")
    print(f"Judgement calls flagged: {len(state['judgement_notes'])}")
    print("\n--- Memo HTML ---\n")
    print(state["memo_html"])

    if not args.publish:
        return 0

    superdocs_key = os.environ.get("SUPERDOCS_API_KEY")
    if not superdocs_key:
        print("\n--publish requires SUPERDOCS_API_KEY.", file=sys.stderr)
        return 1

    print("\n--- Publishing to SuperDocs ---\n")
    client = SuperDocsClient(api_key=superdocs_key)
    try:
        result = publish_memo_to_superdocs(
            state, client, auto_approve=args.auto_approve, export_format=args.format
        )
        print(result)
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
