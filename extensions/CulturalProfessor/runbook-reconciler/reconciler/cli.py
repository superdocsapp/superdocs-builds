"""The command line.

Subcommands are registered in `COMMANDS` and land stage by stage; a command
appears here when it works, so `./rr --help` never advertises something that
answers "not implemented yet".

Every command that can spend a paid operation says so in its own help text.
The default is that nothing spends: `check` and `report` are local and free,
and only `sweep --apply` reaches the SuperDocs API at all.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from reconciler import __version__
from reconciler.config import Config
from reconciler.register import Register
from reconciler.sweep import Sweep, SweepResult

Handler = Callable[[argparse.Namespace], int]


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"runbook-reconciler {__version__}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    """The free layer, end to end. No model, no network, no spend."""
    config = Config.load()
    with Register(config.register_path) as register:
        result = Sweep(config, register).run(mode="check")
        _report(result, verbose=args.verbose)
    # Non-zero when there is drift, so CI can gate on it. `--exit-zero` is for
    # the pre-commit nudge, which must never block a commit.
    return 0 if args.exit_zero or not result.contradictions else 1


def _report(result: SweepResult, verbose: bool = False) -> None:
    if result.coverage_skipped:
        print("coverage: not computed — this sweep was narrowed to specific pages, and a")
        print("          coverage number over part of a space is a wrong coverage number")
    else:
        print(result.coverage.headline())
    print()
    print(result.summary_line())

    if result.contradictions:
        print()
        for finding in sorted(result.contradictions, key=lambda f: (f.page_id or "", f.subject)):
            where = f"page {finding.page_id}" if finding.page_id else "estate"
            print(f"  [{where}] {finding.subject}")
            print(f"      says {_short(finding.detail)}")
            print(f"      observed: {finding.observed}")
            print(f"      evidence: {finding.evidence_file}:{finding.evidence_line or 1}")
            if "comment-only" in finding.tags:
                print("      not editable by this tool: it will post a comment for a human")

    if verbose and result.unverifiable:
        print()
        print(f"could not be checked ({len(result.unverifiable)}):")
        for finding in result.unverifiable:
            print(f"  {finding.subject}: {_short(finding.detail)}")

    print()
    stages = " · ".join(f"{name} {seconds:.2f}s" for name, seconds in result.stages.items())
    print(f"stages: {stages}")
    print(f"operations spent: {result.operations}")


def _short(text: str, limit: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _cmd_measure(args: argparse.Namespace) -> int:
    """Score the checker against the key that was written before it."""
    from reconciler.measure import score, write_raw

    config = Config.load()
    with Register(config.register_path) as register:
        result = Sweep(config, register).run(mode="measure")

    scored = score(result.findings, result.claims)
    for line in scored.lines():
        print(line)
    path = write_raw(scored, result.findings)
    print(f"\nraw data: {path}")
    return 0 if not (scored.misses or scored.false_positives) else 1


COMMANDS: dict[str, tuple[str, Handler]] = {
    "check": (
        "check every runbook against the estate (free: no model, no network, no spend)",
        _cmd_check,
    ),
    "measure": ("score the checker against fixtures/expected.yaml", _cmd_measure),
    "version": ("print the version and exit", _cmd_version),
}

_OPTIONS: dict[str, list[tuple[tuple[str, ...], dict]]] = {
    "check": [
        (
            ("--verbose", "-v"),
            {"action": "store_true", "help": "also list what could not be checked"},
        ),
        (
            ("--exit-zero",),
            {"action": "store_true", "help": "always exit 0, for a non-blocking pre-commit hook"},
        ),
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rr",
        description=(
            "Check operational runbooks against the infrastructure they describe. "
            "Reads DevOps files, writes documents; never the other way round."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, (help_text, handler) in COMMANDS.items():
        child = sub.add_parser(name, help=help_text, description=help_text)
        child.set_defaults(handler=handler)
        for flags, options in _OPTIONS.get(name, []):
            child.add_argument(*flags, **options)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
