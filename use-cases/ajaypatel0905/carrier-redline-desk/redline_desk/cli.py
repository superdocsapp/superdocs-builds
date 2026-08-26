from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import pathlib
import re
import sys
import threading
import time

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


class Progress:
    """Terminal progress while the AI works: a spinner with elapsed time and
    rotating status verbs, plus the AI's own intermediate messages streamed as
    the job reports them. Falls back to plain lines when not on a TTY."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, out=sys.stdout):
        self.out = out
        self.tty = out.isatty()
        self._stop = threading.Event()
        self._thread = None
        self._seen: set = set()
        self._label = ""
        self._verbs: tuple = ("Thinking",)

    def start(self, label: str, verbs: tuple) -> None:
        self._label, self._verbs = label, verbs  # _seen persists: one job's messages print once across waits
        self._stop.clear()
        self._t0 = time.monotonic()
        if self.tty:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            self.out.write(f"  {verbs[0]} — {label}…\n"); self.out.flush()

    def _spin(self) -> None:
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.is_set():
                return
            elapsed = int(time.monotonic() - self._t0)
            verb = self._verbs[min(elapsed // 6, len(self._verbs) - 1)]
            self.out.write(f"\r  {frame} {verb}… {self._label} · {elapsed}s ")
            self.out.flush()
            time.sleep(0.08)

    def on_job(self, job: dict) -> None:
        for msg in (job.get("metadata") or {}).get("intermediate_responses") or []:
            key = (job.get("job_id"), msg.get("sequence"))
            if msg.get("type") == "user_facing" and key not in self._seen:
                self._seen.add(key)
                text = " ".join(str(msg.get("content", "")).split())
                if text:
                    self._clear(); self.out.write(f"  ↳ {text}\n"); self.out.flush()

    def _clear(self) -> None:
        if self.tty:
            self.out.write("\r" + " " * 100 + "\r")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join()
        self._clear()
        self.out.flush()


def _why(change: dict) -> str:
    """The AI's explanation, minus boilerplate that merely restates the proposed
    text (SuperDocs also truncates long explanations with an ellipsis)."""
    why = _plain(change.get("ai_explanation"))
    proposed = _plain(change.get("new_html"))
    if not why or why.startswith("Proposed:") or proposed[:60] in why:
        return ""
    return why


def prompt_reviewer(payload: dict) -> dict:
    print(f"\n{'=' * 70}\nREVIEW — {payload['rule_id']} {payload['rule_name']}  [{payload['severity']}]")
    print(f"Required position: {payload['required_position']}\n")
    decisions = {}
    for change in payload["changes"]:
        print(f"  change {change['change_id'][:8]} · {change['operation']}")
        if change["old_html"]:
            print(f"  CARRIER'S TEXT: {_plain(change['old_html'])}")
        print(f"  PROPOSED TEXT:  {_plain(change['new_html'])}")
        why = _why(change)
        if why:
            print(f"  WHY: {why}")
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
    run.add_argument("--run-name", default="demo", help="run identifier (default: demo); re-using it resumes from the checkpoint")
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
    nodes = RedlineNodes(client, playbook, run_dir, review_mode="auto" if args.auto else "interactive", model_tier=args.model_tier, max_rules=args.max_rules, progress=Progress())
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
        try:
            decisions = prompt_reviewer(interrupts[0].value)
        except (EOFError, KeyboardInterrupt):
            print(f"\n[paused] review stopped before a decision; nothing was applied. Re-run the same command to resume run '{args.run_name}' at this exact clause.")
            return 3
        graph.invoke(Command(resume=decisions), config)

    print(f"\nDone. Outputs in {run_dir}/: redlined_contract.docx, negotiation_summary.docx, summary.json, VERIFICATION.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
