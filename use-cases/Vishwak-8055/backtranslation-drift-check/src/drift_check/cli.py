"""Command-line entry point.

    drift-check run --source S.md --target T.md --source-lang en --target-lang es \\
        --run-id demo --provider fixture --fixture-file bt.json --out-dir out/
    drift-check review --run-json out/demo.json --finding-id F-xxxx --decision approve --reviewer alice
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from drift_check import report
from drift_check.pipeline import run_pipeline
from drift_check.providers.anthropic_provider import AnthropicProvider
from drift_check.providers.fixture import FixtureProvider
from drift_check.review import approve, edit, reject
from drift_check.serialize import finding_from_dict


def _build_provider(args: argparse.Namespace) -> object:
    if args.provider == "fixture":
        if not args.fixture_file:
            raise SystemExit("--fixture-file is required when --provider fixture")
        return FixtureProvider.from_json_file(args.fixture_file)
    return AnthropicProvider()


def cmd_run(args: argparse.Namespace) -> int:
    source_text = Path(args.source).read_text(encoding="utf-8")
    target_text = Path(args.target).read_text(encoding="utf-8")
    provider = _build_provider(args)
    protected_terms = tuple(t.strip() for t in (args.protected_terms or "").split(",") if t.strip())

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run_pipeline(
        run_id=args.run_id,
        source_raw_text=source_text,
        target_raw_text=target_text,
        source_document_id=args.source_id or Path(args.source).stem,
        target_document_id=args.target_id or Path(args.target).stem,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        provider=provider,  # type: ignore[arg-type]
        protected_terms=protected_terms,
        state_dir=out_dir / "state",
        audit_path=out_dir / f"{args.run_id}.audit.jsonl",
    )

    (out_dir / f"{args.run_id}.json").write_text(report.to_json(result), encoding="utf-8")
    (out_dir / f"{args.run_id}.md").write_text(report.to_markdown(result), encoding="utf-8")
    (out_dir / f"{args.run_id}.html").write_text(report.to_html(result), encoding="utf-8")

    summary = report.summary_metrics(result)
    print(json.dumps(summary, indent=2))
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    run_json = json.loads(Path(args.run_json).read_text(encoding="utf-8"))
    matches = [f for f in run_json["findings"] if f["id"] == args.finding_id]
    if not matches:
        print(f"finding {args.finding_id} not found in {args.run_json}", file=sys.stderr)
        return 1
    finding = finding_from_dict(matches[0])

    if args.decision == "approve":
        decision = approve(finding, reviewer=args.reviewer, note=args.note)
    elif args.decision == "reject":
        decision = reject(finding, reviewer=args.reviewer, note=args.note)
    else:
        if not args.text:
            raise SystemExit("--text is required for --decision edit")
        decision = edit(finding, reviewer=args.reviewer, edited_text=args.text, note=args.note)

    print(json.dumps({"decision": decision.decision, "finding_id": decision.finding_id, "reviewer": decision.reviewer}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="drift-check")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the drift check pipeline over a source/target document pair")
    run_p.add_argument("--source", required=True)
    run_p.add_argument("--target", required=True)
    run_p.add_argument("--source-lang", required=True)
    run_p.add_argument("--target-lang", required=True)
    run_p.add_argument("--run-id", required=True)
    run_p.add_argument("--source-id", default=None)
    run_p.add_argument("--target-id", default=None)
    run_p.add_argument("--provider", choices=["fixture", "anthropic"], default="fixture")
    run_p.add_argument("--fixture-file", default=None)
    run_p.add_argument("--protected-terms", default="", help="Comma-separated list of terms that must survive verbatim")
    run_p.add_argument("--out-dir", default="out")
    run_p.set_defaults(func=cmd_run)

    review_p = sub.add_parser(
        "review", help="Record a review decision against a finding in an existing run's JSON report"
    )
    review_p.add_argument("--run-json", required=True)
    review_p.add_argument("--finding-id", required=True)
    review_p.add_argument("--decision", choices=["approve", "reject", "edit"], required=True)
    review_p.add_argument("--reviewer", required=True)
    review_p.add_argument("--text", default=None)
    review_p.add_argument("--note", default=None)
    review_p.set_defaults(func=cmd_review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
