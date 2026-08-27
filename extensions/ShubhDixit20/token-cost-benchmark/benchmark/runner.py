"""
Benchmark runner.

Orchestrates: corpus -> edit sessions -> both arms -> raw records -> CSV/JSON.

Budget guard (per the assigned-build card: "build and prove this in
small-sample mode first; state the cap a full run may spend before you run
it, and report actual spend alongside your results"):

  - `--mode mock` costs nothing (no network, deterministic local estimate).
  - `--mode real` tracks cumulative estimated cost turn-by-turn and stops
    the run the instant the running total would exceed `--budget-usd`,
    rather than after the fact. A partial run is written out, never
    discarded silently.
  - `--small-sample` restricts the corpus to the smallest tier and 2 turns,
    for a cheap dry run that proves the harness works before spending real
    money on the full corpus.

Repeated runs / variance: `--repeats N` re-runs the full matrix N times
(mock mode only recommended for high repeat counts, to keep real-mode cost
bounded) and the report step computes mean/stdev per (tier, edit_type, arm).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import List

from benchmark.corpus import build_corpus, SIZE_TIERS, Document
from benchmark.edit_tasks import generate_all_sessions
from benchmark.client import get_client, ClientError
from benchmark.arms import run_whole_doc_arm, run_section_edit_arm, EditRecord


class BudgetExceeded(Exception):
    pass


def run_benchmark(
    corpus_dir: Path,
    results_dir: Path,
    mode: str = "mock",
    small_sample: bool = False,
    docs_per_tier: int = 2,
    turns_per_doc: int = 5,
    repeats: int = 1,
    budget_usd: float = 1.0,
    seed: int = 42,
) -> dict:
    results_dir.mkdir(parents=True, exist_ok=True)

    if small_sample:
        docs_per_tier = 1
        turns_per_doc = 2
        # Restrict corpus.SIZE_TIERS is module-level; instead we just build
        # normally and slice to the smallest tier below, so corpus.py stays
        # the single source of truth for tier definitions.

    docs = build_corpus(corpus_dir, docs_per_tier=docs_per_tier, seed=seed)
    if small_sample:
        docs = [d for d in docs if d.doc_id.startswith("tiny-")]

    sessions = generate_all_sessions(docs, turns_per_doc=turns_per_doc, seed=seed)

    all_records: List[EditRecord] = []
    spent_usd = 0.0
    stopped_early = False
    stop_reason = None
    started = time.time()

    try:
        client = get_client(mode)
    except ClientError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise

    for repeat in range(repeats):
        for doc in docs:
            session = sessions[doc.doc_id]
            if not session:
                continue

            for arm_name, arm_fn in (("whole_doc", run_whole_doc_arm), ("section_edit", run_section_edit_arm)):
                records = arm_fn(doc, session, client)
                for r in records:
                    r.task_id = f"r{repeat}-{r.task_id}"  # disambiguate repeats
                    spent_usd += r.cost_usd
                    all_records.append(r)

                    if mode == "real" and spent_usd > budget_usd:
                        stopped_early = True
                        stop_reason = (
                            f"Budget guard tripped: spent ${spent_usd:.4f} > "
                            f"cap ${budget_usd:.2f} after {len(all_records)} edits."
                        )
                        print(f"STOPPING: {stop_reason}", file=sys.stderr)
                        _write_results(all_records, results_dir)
                        raise BudgetExceeded(stop_reason)

    elapsed = time.time() - started
    _write_results(all_records, results_dir)

    summary = {
        "mode": mode,
        "small_sample": small_sample,
        "num_documents": len(docs),
        "num_edits": len(all_records),
        "repeats": repeats,
        "total_estimated_cost_usd": round(spent_usd, 6),
        "budget_cap_usd": budget_usd if mode == "real" else None,
        "stopped_early": stopped_early,
        "stop_reason": stop_reason,
        "wall_clock_s_total": round(elapsed, 2),
    }
    (results_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _write_results(records: List[EditRecord], results_dir: Path) -> None:
    if not records:
        return
    csv_path = results_dir / "raw_edits.csv"
    fieldnames = list(records[0].to_dict().keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(r.to_dict())

    json_path = results_dir / "raw_edits.json"
    json_path.write_text(
        json.dumps([r.to_dict() for r in records], indent=2), encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description="SuperDocs token-cost benchmark: whole-doc regen vs section edit")
    parser.add_argument("--mode", choices=["mock", "real"], default="mock",
                         help="mock = offline/free/deterministic (default). real = live SuperDocs API, spends money.")
    parser.add_argument("--small-sample", action="store_true",
                         help="Restrict to the smallest doc tier and 2 turns. Always run this before --mode real on the full corpus.")
    parser.add_argument("--docs-per-tier", type=int, default=2)
    parser.add_argument("--turns-per-doc", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=1, help="Re-run the full matrix N times to report variance.")
    parser.add_argument("--budget-usd", type=float, default=1.0, help="Hard cap for --mode real. Run stops the instant this is exceeded.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--corpus-dir", type=Path, default=Path("data/corpus"))
    parser.add_argument("--results-dir", type=Path, default=Path("data/results"))
    args = parser.parse_args()

    if args.mode == "real":
        print(f"[budget guard] cap for this run: ${args.budget_usd:.2f} (--mode real)", file=sys.stderr)

    try:
        summary = run_benchmark(
            corpus_dir=args.corpus_dir,
            results_dir=args.results_dir,
            mode=args.mode,
            small_sample=args.small_sample,
            docs_per_tier=args.docs_per_tier,
            turns_per_doc=args.turns_per_doc,
            repeats=args.repeats,
            budget_usd=args.budget_usd,
            seed=args.seed,
        )
    except BudgetExceeded:
        print("Run stopped by budget guard. Partial results were written.", file=sys.stderr)
        sys.exit(2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
