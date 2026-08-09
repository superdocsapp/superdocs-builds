"""Command-line entry point.

Usage:
    python -m delta_applier.cli run                     # interactive review, bundled fixtures
    python -m delta_applier.cli run --auto-approve       # non-interactive, approve every staged change
    python -m delta_applier.cli run --proposal my.docx --amendments a1.txt,a2.txt --qna q1.txt
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

from .models import ReviewItem
from .orchestrator import DeltaApplierRun
from .superdocs_client import SuperDocsClient

HERE = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURES = HERE / "fixtures"
DEFAULT_CONFIG = HERE / "config" / "section_map.yaml"
DEFAULT_OUT = HERE / "output"


def interactive_decide(items: List[ReviewItem]) -> Dict[str, Tuple[bool, Optional[str]]]:
    decisions: Dict[str, Tuple[bool, Optional[str]]] = {}
    section = items[0].section_id if items else "?"
    print(f"\n--- {len(items)} proposed change(s) for section '{section}' ---")
    for item in items:
        print(f"\nchange_id={item.change_id} operation={item.operation}")
        print(f"  cited from: {', '.join(d.source.citation() for d in item.deltas)}")
        print(f"  AI explanation: {item.ai_explanation}")
        if item.old_html:
            print(f"  OLD: {item.old_html[:200]}")
        if item.new_html:
            print(f"  NEW: {item.new_html[:200]}")
        answer = input("  Approve this change? [y/N]: ").strip().lower()
        approved = answer == "y"
        decisions[item.change_id] = (approved, None if approved else "rejected via CLI review")
    return decisions


def auto_approve(items: List[ReviewItem]) -> Dict[str, Tuple[bool, Optional[str]]]:
    return {i.change_id: (True, None) for i in items}


def main(argv: Optional[List[str]] = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Amendment and Q&A Delta Applier")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the full pipeline")
    run_p.add_argument("--solicitation", default=str(DEFAULT_FIXTURES / "solicitation.txt"))
    run_p.add_argument(
        "--amendments",
        default=str(DEFAULT_FIXTURES / "amendment_0001.txt"),
        help="Comma-separated amendment files, in arrival order",
    )
    run_p.add_argument("--qna", default=str(DEFAULT_FIXTURES / "qna_0001.txt"))
    run_p.add_argument("--proposal", default=str(DEFAULT_FIXTURES / "proposal_draft.html"))
    run_p.add_argument("--config", default=str(DEFAULT_CONFIG))
    run_p.add_argument("--session-id", default="delta-applier-demo")
    run_p.add_argument("--out", default=str(DEFAULT_OUT))
    run_p.add_argument("--auto-approve", action="store_true")
    run_p.add_argument("--format", default="docx", choices=["docx", "pdf", "html", "markdown", "txt"])
    run_p.add_argument("--solicitation-no", default="FA8750-26-R-0042")
    run_p.add_argument("--model-tier", default=None)

    args = parser.parse_args(argv)

    if args.command != "run":
        return 1

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        print("SUPERDOCS_API_KEY is not set (checked environment and .env). Aborting.", file=sys.stderr)
        return 1
    base_url = os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app")

    client = SuperDocsClient(api_key=api_key, base_url=base_url)
    run = DeltaApplierRun(client, args.config, args.session_id)

    solicitation_path = Path(args.solicitation)
    run.ingest_baseline(solicitation_path.read_text(encoding="utf-8"), solicitation_path.name)
    for amendment_path in args.amendments.split(","):
        p = Path(amendment_path.strip())
        run.ingest_amendment(p.read_text(encoding="utf-8"), p.name)
    qna_path = Path(args.qna)
    run.ingest_qna(qna_path.read_text(encoding="utf-8"), qna_path.name)

    impacts = run.compute_impacts()
    n_direct = sum(1 for i in impacts.values() if i.order == "direct")
    n_second = sum(1 for i in impacts.values() if i.order == "second_order")
    print(f"\n{len(run.deltas)} amendment delta(s) detected.")
    print(f"{len(impacts)} proposal section(s) affected ({n_direct} direct, {n_second} second-order).")
    if run.conflicts:
        print(f"\n\u26a0 {len(run.conflicts)} conflict(s) detected \u2014 see the log for details.")

    run.load_proposal(args.proposal)

    decide_fn = auto_approve if args.auto_approve else interactive_decide
    run.run_all(decide_fn, model_tier=args.model_tier)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    export_path = out_dir / f"proposal-final.{args.format}"
    run.export_proposal(str(export_path), format=args.format)
    print(f"\nExported final proposal to {export_path}")

    log_text = run.build_log(args.solicitation_no)
    log_path = out_dir / "amendment-response-log.md"
    log_path.write_text(log_text, encoding="utf-8")
    print(f"Wrote amendment-response log to {log_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
