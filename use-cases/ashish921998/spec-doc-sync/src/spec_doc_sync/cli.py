from __future__ import annotations

import argparse
from pathlib import Path

from .apply import apply_plan
from .io import load_plan, save_plan
from .planner import build_plan
from .superdocs import SuperDocsClient


def make_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="spec-doc-sync")
    commands = root.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="no-spend preview; makes no SuperDocs calls")
    plan.add_argument("--previous", type=Path, required=True); plan.add_argument("--current", type=Path, required=True)
    plan.add_argument("--docs", type=Path, required=True); plan.add_argument("--out", type=Path, default=Path("plan.json")); plan.add_argument("--state", type=Path)
    review = commands.add_parser("review", help="item-by-item writer decisions")
    review.add_argument("plan", type=Path)
    apply = commands.add_parser("apply", help="apply only approved local edits")
    apply.add_argument("plan", type=Path); apply.add_argument("--docs", type=Path, required=True); apply.add_argument("--state", type=Path, default=Path(".spec-doc-sync-state.json"))
    live = commands.add_parser("live", help="send approved intents through SuperDocs review")
    live.add_argument("plan", type=Path); live.add_argument("--docs", type=Path, required=True)
    live.add_argument("--export-dir", type=Path, help="optional directory for reviewed DOCX exports")
    return root


def main() -> None:
    args = make_parser().parse_args()
    if args.command == "plan":
        value = build_plan(args.previous, args.current, args.docs, args.state)
        save_plan(value, args.out)
        print(f"Preview written to {args.out}: {len(value.changes)} changes, {len(value.proposals)} proposals")
        if value.stop_reason: print(f"Stopped: {value.stop_reason}")
    elif args.command == "review":
        value = load_plan(args.plan)
        for item in value.proposals:
            if item.decision == "escalated":
                print(f"ESCALATED {item.rationale}"); continue
            answer = input(f"\n{item.file}: {item.rationale}\nApprove? [y/N] ").strip().lower()
            item.decision = "approved" if answer == "y" else "rejected"
            if item.decision == "rejected": item.feedback = input("Feedback (optional): ")
        save_plan(value, args.plan); print("Decisions saved")
    elif args.command == "apply":
        value = load_plan(args.plan)
        print(apply_plan(value, args.docs, args.state))
    elif args.command == "live":
        value = load_plan(args.plan); client = SuperDocsClient()
        for item in value.proposals:
            if item.decision != "approved" or not item.file: continue
            def decide(change: dict) -> tuple[bool, str]:
                print(f"\n{change.get('ai_explanation','Proposed change')}\nBEFORE: {change.get('old_html','')}\nAFTER: {change.get('new_html','')}")
                approved = input("Approve this SuperDocs change? [y/N] ").strip().lower() == "y"
                return approved, "" if approved else input("Feedback: ")
            result = client.propose(args.docs / item.file, item, decide)
            print(f"Completed SuperDocs review for {item.file}: {result.get('status')}")
            if args.export_dir:
                args.export_dir.mkdir(parents=True, exist_ok=True)
                destination = args.export_dir / f"{Path(item.file).stem}-reviewed.docx"
                destination.write_bytes(client.export(result["session_id"], destination.name))
                print(f"Exported {destination}")


if __name__ == "__main__": main()
