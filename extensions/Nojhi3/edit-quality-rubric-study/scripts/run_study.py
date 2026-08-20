"""Run the study end to end with budget-guard discipline.

Usage:
    python scripts/run_study.py --small          # 6 cases (budget-conscious demo)
    python scripts/run_study.py --full           # all 11 cases
    python scripts/run_study.py --edits plan-01  # only the edit pipeline
    python scripts/run_study.py --judge-auto     # only the automated judge
    python scripts/run_study.py --report         # assemble + export the report

Cap: stated before every run; enforced per billable call in app/budget.py.
Actual spend is printed after every step.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.budget import BudgetGuard  # noqa: E402
from app.judges import get_judge, load_score_sheets  # noqa: E402
from app.pipeline import EditRunner, load_cases  # noqa: E402
from app.report import build_report  # noqa: E402
from app.superdocs_client import SuperDocsClient  # noqa: E402


def print_budget(label: str):
    report = BudgetGuard().report()
    print(f"[budget] {label}: spent {report['spent_ops']}/{report['cap_ops']} ops "
          f"({report['billable_calls']} billable calls)")


def main():
    parser = argparse.ArgumentParser(description="Edit-Quality Rubric study runner")
    parser.add_argument("--small", action="store_true", help="small-sample: first 6 cases")
    parser.add_argument("--full", action="store_true", help="full run: all cases")
    parser.add_argument("--edits", nargs="*", default=None, help="only run edit pipeline for these case_ids")
    parser.add_argument("--judge-auto", nargs="*", default=None, help="only run automated judge (no ids = small sample)")
    parser.add_argument("--report", action="store_true", help="assemble report and export via SuperDocs")
    parser.add_argument("--cap", type=int, default=None, help="override budget cap (ops)")
    args = parser.parse_args()

    budget = BudgetGuard(cap_ops=args.cap) if args.cap is not None else BudgetGuard()
    client = SuperDocsClient(budget=budget)

    cases = load_cases()
    if args.small:
        selected = [c["case_id"] for c in cases[: config.SMALL_SAMPLE_CASES]]
    elif args.full:
        selected = [c["case_id"] for c in cases]
    else:
        selected = None

    print("=" * 72)
    print("EDIT-QUALITY RUBRIC + HUMAN-vs-AUTO AGREEMENT STUDY")
    print("=" * 72)
    print(f"Cap stated before this run: {budget.cap_ops} operations.")
    whoami = client.account_status()
    quota = whoami.get("quota") or {}
    print(f"Account: {whoami.get('account_id', '?')} | tier: {whoami.get('tier', '?')} | "
          f"remaining ops: {quota.get('remaining', '?')} | used: {quota.get('used', '?')}")
    print(f"Cases selected: {selected or 'all'}")
    print()

    if args.edits is not None:
        ids = args.edits or selected
        print(f">>> EDIT PIPELINE for {ids}")
        t0 = time.time()
        summary = EditRunner(client).run_all(ids)
        print(f">>> done in {time.time() - t0:.0f}s "
              f"({sum(1 for r in summary['results'] if r['status'] == 'completed')} completed, "
              f"{len(summary['failed'])} failed)")
        for f in summary["failed"]:
            print("    failed:", f)
        print_budget("after edits")
        return

    if args.judge_auto is not None:
        ids = args.judge_auto or selected
        print(f">>> AUTOMATED JUDGE for {ids} (provider={config.JUDGE_PROVIDER})")
        t0 = time.time()
        summary = get_judge().judge_all(ids)
        print(f">>> done in {time.time() - t0:.0f}s "
              f"({sum(1 for r in summary['results'] if r['status'] == 'completed')} judged, "
              f"{len(summary['failed'])} failed)")
        for f in summary["failed"]:
            print("    failed:", f)
        print_budget("after auto judge")
        return

    if args.report:
        md = build_report(budget)
        out = config.REPORT_DIR / "study_report.md"
        out.write_text(md, encoding="utf-8")
        print(f">>> report written to {out}")
        print_budget("after report")
        return

    if not selected:
        parser.print_help()
        return

    print(f">>> EDIT PIPELINE ({len(selected)} cases)")
    t0 = time.time()
    summary = EditRunner(client).run_all(selected)
    ok = sum(1 for r in summary["results"] if r["status"] == "completed")
    print(f">>> edits done in {time.time() - t0:.0f}s: {ok}/{len(selected)} completed")
    for f in summary["failed"]:
        print("    failed:", f)
    print_budget("after edits")
    print()

    print(">>> HUMAN JUDGING")
    print("Open the judge UI:  uvicorn app.main:app  ->  http://127.0.0.1:8000/judge")
    print("Score every completed case, then press Enter here to continue with the auto judge.")
    input("Press Enter when human scores are saved...")

    print()
    print(f">>> AUTOMATED JUDGE ({len(selected)} cases, provider={config.JUDGE_PROVIDER})")
    t0 = time.time()
    summary = get_judge().judge_all(selected)
    print(f">>> done in {time.time() - t0:.0f}s "
          f"({sum(1 for r in summary['results'] if r['status'] == 'completed')} judged)")
    for f in summary["failed"]:
        print("    failed:", f)
    print_budget("after auto judge")
    print()

    human, auto = load_score_sheets("human"), load_score_sheets("auto")
    print(f">>> sheets: human={len(human)} auto={len(auto)}")

    md = build_report(budget)
    out = config.REPORT_DIR / "study_report.md"
    out.write_text(md, encoding="utf-8")
    print(f">>> report written to {out}")
    print_budget("final")
    print("Next: export the report through SuperDocs with --report-export or the API.")


if __name__ == "__main__":
    main()