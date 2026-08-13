#!/usr/bin/env python3
"""Runs the close-package assembler end to end on one of the bundled
fixture contracts.

Usage:
    python run_demo.py                                    # build the package only
    python run_demo.py --contract saas                     # pick a fixture
    python run_demo.py --publish                            # also push to SuperDocs
    python run_demo.py --publish --auto-approve              # publish, auto-resolving
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

from close_package.runner import build_close_package, publish_package_to_superdocs
from core.llm import LLMClient
from core.superdocs_client import SuperDocsClient

FIXTURES = {
    "saas": "tests/fixtures/drafter/contract_saas_bundled.txt",
    "milestones": "tests/fixtures/drafter/contract_services_milestones.txt",
    "hardware": "tests/fixtures/drafter/contract_hardware_warranty.txt",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", choices=FIXTURES, default="hardware")
    parser.add_argument(
        "--publish", action="store_true", help="Also push the close package through SuperDocs (HITL)."
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

    print(f"Building a close package from {contract_path.name}...\n")
    state = build_close_package(str(contract_path), llm)

    analysis = state["memo_state"]["analysis"]
    print(f"Performance obligations found: {len(analysis['performance_obligations'])}")
    print(f"Schedule facts extracted: {len(state['schedule']['schedule_facts'])}")
    print(f"Schedule entries computed: {len(state['schedule']['entries'])}")
    print(f"Audit trail entries: {len(state['audit_trail'])}")
    flagged = sum(1 for e in state["schedule"]["entries"] if e["requires_human_review"])
    print(f"Schedule entries flagged for human review: {flagged}")
    print("\n--- Close Package HTML ---\n")
    print(state["package_html"])

    if not args.publish:
        return 0

    superdocs_key = os.environ.get("SUPERDOCS_API_KEY")
    if not superdocs_key:
        print("\n--publish requires SUPERDOCS_API_KEY.", file=sys.stderr)
        return 1

    print("\n--- Publishing to SuperDocs ---\n")
    client = SuperDocsClient(api_key=superdocs_key)
    try:
        result = publish_package_to_superdocs(
            state, client, auto_approve=args.auto_approve, export_format=args.format
        )
        print(result)
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
