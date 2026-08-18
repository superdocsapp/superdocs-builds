from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import re
import sys

from langgraph.types import Command

from .graph import RedlineNodes, build_graph, open_checkpointer
from .playbook import load_playbook
from .superdocs import SuperDocsClient


def _load_env(path: pathlib.Path = pathlib.Path(".env")) -> None:
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _plain(html: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def prompt_reviewer(payload: dict) -> dict:
    print(f"\n{'=' * 70}\nREVIEW — {payload['rule_id']} {payload['rule_name']}  [{payload['severity']}]")
    print(f"Required position: {payload['required_position']}\n")
    decisions = {}
    for change in payload["changes"]:
        print(f"  change {change['change_id'][:8]} · {change['operation']}")
        if change["old_html"]:
            print(f"  CARRIER'S TEXT: {_plain(change['old_html'])}")
        print(f"  PROPOSED TEXT:  {_plain(change['new_html'])}")
        print(f"  WHY: {_plain(change.get('ai_explanation'))}")
        while True:
            answer = input("  approve? [y]es / [n]o / n + feedback (e.g. `n keep the cap wording`): ").strip()
            if answer.lower().startswith("y"):
                decisions[change["change_id"]] = {"approved": True}
                break
            if answer.lower().startswith("n"):
                feedback = answer[1:].strip() or None
                decisions[change["change_id"]] = {"approved": False, "feedback": feedback}
                break
    return decisions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="redline_desk", description="Carrier & shipper contract redline desk, built on SuperDocs.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run (or resume) a redline over a carrier contract")
    run.add_argument("--contract", required=True, type=pathlib.Path)
    run.add_argument("--playbook", required=True, type=pathlib.Path)
    run.add_argument("--run-name", required=True, help="run identifier; re-using it resumes from the checkpoint")
    run.add_argument("--auto", action="store_true", help="approve every in-scope proposal (machine mode); default is interactive review")
    run.add_argument("--model-tier", default=None, choices=["core", "turbo", "pro", "max"])
    run.add_argument("--max-rules", type=int, default=None, help="small-sample mode: process only the first N planned rules")
    sub.add_parser("mermaid", help="print the pipeline graph as Mermaid (for the architecture diagram)")
    args = parser.parse_args(argv)

    if args.cmd == "mermaid":
        nodes = RedlineNodes(client=None, playbook=None, run_dir=pathlib.Path("."), review_mode="auto")  # type: ignore[arg-type]
        print(build_graph(nodes).get_graph().draw_mermaid())
        return 0

    _load_env()
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        print("SUPERDOCS_API_KEY is not set (env var or .env file).", file=sys.stderr)
        return 2

    run_dir = pathlib.Path("runs") / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    client = SuperDocsClient(api_key)
    playbook = load_playbook(args.playbook)
    nodes = RedlineNodes(client, playbook, run_dir, review_mode="auto" if args.auto else "interactive", model_tier=args.model_tier, max_rules=args.max_rules)
    checkpointer = open_checkpointer(run_dir)
    graph = build_graph(nodes, checkpointer)
    config = {"configurable": {"thread_id": args.run_name}}

    digest = hashlib.sha256(args.contract.read_bytes()).hexdigest()[:12]
    fresh = graph.get_state(config).created_at is None
    initial = {"contract_path": str(args.contract), "session_id": f"redline-{args.run_name}-{digest}"} if fresh else None
    if not fresh:
        print(f"[resume] continuing run '{args.run_name}' from its checkpoint")

    graph.invoke(initial, config)
    while (snapshot := graph.get_state(config)).next:
        interrupts = [i for t in snapshot.tasks for i in t.interrupts]
        if not interrupts:
            graph.invoke(None, config)
            continue
        graph.invoke(Command(resume=prompt_reviewer(interrupts[0].value)), config)

    print(f"\nDone. Outputs in {run_dir}/: redlined_contract.docx, negotiation_summary.docx, summary.json, VERIFICATION.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
