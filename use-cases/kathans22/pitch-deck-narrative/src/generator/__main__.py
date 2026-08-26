"""CLI: ``python -m generator run --vertical legal``.

Loads ``SUPERDOCS_API_KEY`` from the environment (or a local ``.env`` if present).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from project ``.env`` without overriding existing env."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m generator",
        description=(
            "ClarityDocs pitch-script generator — speaking scripts only, never a slide deck."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser(
        "run",
        help="Generate, guard, and score one vertical (idempotent per manifest version).",
    )
    run_parser.add_argument(
        "--vertical",
        required=True,
        help="Vertical code from config/verticals/ (e.g. legal, fintech).",
    )
    run_parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore idempotent skip and regenerate even if exports exist.",
    )

    score_parser = sub.add_parser(
        "score",
        help="Run divergence.score_all across exported narratives (0 SuperDocs ops).",
    )
    score_parser.add_argument(
        "--from",
        dest="narratives_from",
        default="evidence/narratives",
        help="Directory of pitch-script-*.md files (default: evidence/narratives).",
    )
    return parser


async def _cmd_run(vertical: str, *, force: bool) -> int:
    from .service import run_vertical

    result = await run_vertical(vertical, force=force)
    print(f"vertical={result['vertical']}")
    print(f"skipped={result['skipped']}")
    print(f"ledger_status={result['ledger_status']}")
    print(f"guard={result['guard']}")
    print(f"ops_total={result['ops_total']}")
    print(f"paths={result['paths']}")
    score = result.get("score") or {}
    print(f"score_status={score.get('status')}")
    if score.get("reason"):
        print(f"score_reason={score['reason']}")
    if score.get("report_path"):
        print(f"score_report={score['report_path']}")
    return 0


def _cmd_score(narratives_from: str) -> int:
    from .service import EVIDENCE_DIR, score_available

    source = Path(narratives_from)
    if not source.is_absolute():
        source = Path(__file__).resolve().parents[2] / source
    result = score_available(
        narratives_dir=source,
        report_path=EVIDENCE_DIR / "divergence-report.json",
    )
    if result.get("status") == "deferred":
        print(f"score_status=deferred")
        print(f"score_reason={result.get('reason')}")
        return 1
    evaluation = result.get("evaluation") or {}
    aggregates = (result.get("report") or {}).get("aggregates") or {}
    print(f"verdict={result.get('verdict')}")
    print(f"verticals={result.get('verticals')}")
    print(f"mean_vertical_overlap={aggregates.get('mean_vertical_overlap')}")
    print(f"mean_shared_overlap={aggregates.get('mean_shared_overlap')}")
    print(f"passed={evaluation.get('passed')}")
    for failure in evaluation.get("failures") or []:
        print(f"failure={failure}")
    for note in result.get("coverage_notes") or []:
        print(
            f"coverage={note['vertical']} section {note['section']}: {note['issue']}"
        )
    for cell in (result.get("highest_vertical_cells") or [])[:8]:
        mark = " HOT" if cell.get("at_or_above_section_max") else ""
        print(
            f"vertical_cell section {cell['section']} "
            f"{cell['vertical_a']}<->{cell['vertical_b']}: {cell['score']:.3f}{mark}"
        )
    print(f"score_report={result.get('report_path')}")
    return 0 if evaluation.get("passed") else 1


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    os.environ.setdefault("SUPERDOCS_CHAT_BATCH_CAP", "2")
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        key = os.environ.get("SUPERDOCS_API_KEY", "")
        if not key or key == "your-key-here":
            print(
                "SUPERDOCS_API_KEY is missing or still the placeholder. "
                "Fix: set it in the environment or in a local .env (never commit the key).",
                file=sys.stderr,
            )
            return 2
        return asyncio.run(_cmd_run(args.vertical, force=args.force))

    if args.command == "score":
        return _cmd_score(args.narratives_from)

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
