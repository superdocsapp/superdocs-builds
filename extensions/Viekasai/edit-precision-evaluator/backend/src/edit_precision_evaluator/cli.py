from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .budget import BudgetExceeded
from .config import Settings
from .corpus import load_corpus, validate_corpus
from .models import Approach
from .runner import run_evaluation, write_report
from .superdocs_client import SuperDocsClient


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _validate(args: argparse.Namespace) -> int:
    errors = validate_corpus(args.corpus, args.documents)
    cases = load_corpus(args.corpus)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    review_counts: dict[str, int] = {}
    for case in cases:
        review_counts[case.review_status.value] = review_counts.get(case.review_status.value, 0) + 1
    print(f"Validated {len(cases)} cases")
    print("Review status: " + ", ".join(f"{key}={value}" for key, value in review_counts.items()))
    return 0


def _approaches(value: str) -> set[Approach]:
    if value == "both":
        return {Approach.DIRECT, Approach.SEARCH_SCOPED}
    return {Approach(value)}


async def _run_live_async(args: argparse.Namespace) -> int:
    errors = validate_corpus(args.corpus, args.documents)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    cases = load_corpus(args.corpus)
    settings = Settings.from_environment()
    try:
        async with SuperDocsClient(settings) as client:
            report = await run_evaluation(
                client=client,
                cases=cases,
                document_root=args.documents,
                approaches=_approaches(args.approach),
                operation_cap=args.max_operations,
                mode=args.mode,
                export_root=args.output.parent / "exports",
                checkpoint_path=args.output.parent / "checkpoint.json",
            )
    except BudgetExceeded as exc:
        print(f"BUDGET STOP: {exc}")
        return 2
    except ValueError as exc:
        print(f"VALIDATION STOP: {exc}")
        return 3
    write_report(report, args.output)
    print(f"Wrote {len(report['results'])} results to {args.output}")
    print(
        f"Operations: {report['actual_operations']}/{report['operation_cap']} | "
        f"Coverage: {report['overall']['intended_change_coverage']:.1%} | "
        f"Collateral: {report['overall']['collateral_damage_rate']:.1%}"
    )
    return 0


def _run_live(args: argparse.Namespace) -> int:
    return asyncio.run(_run_live_async(args))


def build_parser() -> argparse.ArgumentParser:
    project_root = _default_project_root()
    parser = argparse.ArgumentParser(description="SuperDocs edit-precision evaluator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-corpus", help="Validate corpus labels and files")
    validate.add_argument("--corpus", type=Path, default=project_root / "corpus/cases.jsonl")
    validate.add_argument("--documents", type=Path, default=project_root / "corpus/documents")
    validate.set_defaults(handler=_validate)

    run_live = subparsers.add_parser(
        "run-live", help="Run the labelled corpus against the live SuperDocs API"
    )
    run_live.add_argument("--corpus", type=Path, default=project_root / "corpus/cases.jsonl")
    run_live.add_argument("--documents", type=Path, default=project_root / "corpus/documents")
    run_live.add_argument("--mode", choices=["small", "full"], default="small")
    run_live.add_argument("--approach", choices=["direct", "search_scoped", "both"], default="both")
    run_live.add_argument(
        "--max-operations",
        type=int,
        required=True,
        help="Hard operation cap declared before the run (small/both estimates 12)",
    )
    run_live.add_argument("--output", type=Path, default=project_root / "results/live/latest.json")
    run_live.set_defaults(handler=_run_live)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
