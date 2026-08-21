"""Command line.

Seven verbs. The first four cost nothing and need no API key, which is
deliberate — the useful half of this tool is the half that tells you what is
out of step, and that half should be free enough to put in a pre-commit hook.

    docsync facts       what the code currently says
    docsync audit       do the documents actually contain what they claim to
    docsync plan        what has drifted, which documents carry it, what it costs
    docsync snapshot    record the current values as the baseline

    docsync apply       send the edits, review each one, verify, write back
    docsync approve     decide a batch that was staged earlier
    docsync serve       run as an MCP server for Cursor / VS Code / Claude Code

``apply`` is the only command that spends anything, and ``--dry-run`` prints
exactly what it would send and what it would cost without making a call.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from docsync.apply import apply_interactive, commit
from docsync.facts import SourceError
from docsync.plan import AUDIT_UNRESOLVED, AUDIT_WEAK
from docsync.registry import RegistryError
from docsync.report import (
    render_audit,
    render_facts,
    render_pending,
    render_plan,
    render_report,
)
from docsync.state import Pending, PendingChange, PendingJob, StateError
from docsync.superdocs import BudgetExceeded, SuperDocsError
from docsync.workspace import Workspace


def _say(*parts: object) -> None:
    print(*parts, flush=True)


def _rule(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m", flush=True)


# ---------------------------------------------------------------------------
# Free commands
# ---------------------------------------------------------------------------


def cmd_facts(args: argparse.Namespace) -> int:
    workspace = Workspace.open(args.registry)
    table = workspace.facts_now()
    if args.json:
        _say(json.dumps({k: v.text for k, v in table.values.items() if v.ok}, indent=2))
    else:
        _say(render_facts(table))
    return 1 if table.errors else 0


def cmd_audit(args: argparse.Namespace) -> int:
    workspace = Workspace.open(args.registry)
    findings = workspace.audit()
    _rule("Coverage")
    _say(render_audit(findings))

    uncovered = workspace.registry.uncovered_facts()
    if uncovered:
        _rule("Facts no document carries")
        for key in uncovered:
            _say(f"  {key}")
        _say("\n  Not an error — but a change to any of these would update nothing.")

    failed = [f for f in findings if f.status == AUDIT_UNRESOLVED]
    weak = [f for f in findings if f.status == AUDIT_WEAK]
    if weak and not failed:
        _say(f"\n  {len(weak)} weak anchor(s). These still work; they are just worth tightening.")
    return 1 if failed else 0


def cmd_plan(args: argparse.Namespace) -> int:
    workspace = Workspace.open(args.registry)
    plan = workspace.plan(base=args.base, base_dir=args.base_dir, allow_prose=args.allow_prose)
    _say(render_plan(plan, show_instruction=args.show_instruction or ""))
    if plan.blocked:
        return 2
    return 0 if plan.changes else 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    workspace = Workspace.open(args.registry)
    count = workspace.snapshot()
    _say(f"  recorded {count} fact value(s) as the baseline → {workspace.state.path}")
    return 0


# ---------------------------------------------------------------------------
# Spending commands
# ---------------------------------------------------------------------------


MAX_ROUNDS = 12


def cmd_apply(args: argparse.Namespace) -> int:
    """Apply every outstanding change, one fact per document per round.

    A document with three changed facts takes three rounds against the same
    session, because a turn carrying more than one instruction item is
    measurably unreliable — see ``DocumentPlan.this_round``. The rounds run
    back to back here so that is a cost, not a chore.
    """
    workspace = Workspace.open(args.registry)
    reviewer = _auto_approve if args.yes else _terminal_reviewer()
    spent = 0
    round_no = 0
    previous: set[tuple[str, str]] | None = None

    while True:
        round_no += 1
        plan = workspace.plan(
            base=args.base, base_dir=args.base_dir, allow_prose=args.allow_prose
        )

        # A round that leaves exactly the work it started with is not going to
        # succeed on the next attempt either, and each one costs operations.
        # This caught a real loop: write-back refused to overwrite the previous
        # round's own output, so the file never advanced and the same edit was
        # planned for ever.
        outstanding = {
            (doc.path, change.key) for doc in plan.documents for change in doc.to_send
        }
        if previous is not None and outstanding and outstanding == previous:
            _say(
                f"\n  Stopping: round {round_no - 1} changed nothing on disk, so this round "
                f"would send the same edits again. Outstanding: "
                + ", ".join(f"{path} · {key}" for path, key in sorted(outstanding))
                + "\n  The result above says why each one was not written back."
            )
            return 1
        previous = outstanding

        _rule("Plan" if round_no == 1 else f"Plan — round {round_no}")
        _say(render_plan(plan, show_instruction=args.show_instruction or ""))

        if plan.blocked:
            _say(
                "\n  Refusing to send anything. A fact that cannot be read has no new "
                "value, and writing a guess into a document is the failure this tool "
                "exists to prevent."
            )
            return 2
        if not any(doc.this_round for doc in plan.documents):
            if round_no > 1:
                _say("\n  Everything that could be applied has been.")
            return 0

        if args.dry_run:
            _rule("Dry run")
            _say(
                f"  Nothing was sent and nothing was billed. This change needs "
                f"{plan.rounds} round(s). Re-run without --dry-run to apply."
            )
            return 0

        if spent + plan.operations > args.max_operations:
            _say(
                f"\n  Refusing: this round needs {plan.operations} operations, {spent} have "
                f"already been spent, and the budget is {args.max_operations}. Raise "
                f"--max-operations or narrow the change."
            )
            return 2
        if round_no > MAX_ROUNDS:
            _say(f"\n  stopping after {MAX_ROUNDS} rounds — this is not converging")
            return 1

        if args.yes and round_no == 1:
            _say("\n  --yes: every proposed change will be approved without anyone reading it.")

        with workspace.client(max_operations=args.max_operations - spent) as client:
            if round_no == 1:
                _report_quota(client)
            try:
                _, report = apply_interactive(
                    client,
                    plan,
                    workspace.state,
                    session_prefix=workspace.session_id,
                    review=reviewer,
                    model_tier=args.model_tier,
                    write_back=not args.no_write_back,
                    force_write=args.force_write,
                    on_progress=(
                        (lambda who, msg: _say(f"    {who}: {msg}")) if args.verbose else None
                    ),
                )
            except BudgetExceeded as exc:
                _say(f"\n  stopped: {exc}")
                return 2
            spent += client.ledger.billable

            _rule("Result" if round_no == 1 else f"Result — round {round_no}")
            _say(render_report(report))

        if not report.ok:
            _say(
                "\n  Stopping. Something did not land, and the baseline for it was not "
                "moved, so it will show up again on the next run. Read the affected "
                "document before committing."
            )
            workspace.advance_baseline(
                base=args.base, base_dir=args.base_dir, allow_prose=args.allow_prose
            )
            return 1

        advanced = workspace.advance_baseline(
            base=args.base, base_dir=args.base_dir, allow_prose=args.allow_prose
        )
        if advanced:
            _say(f"\n  baseline advanced for: {', '.join(advanced)}")


def cmd_approve(args: argparse.Namespace) -> int:
    """Decide a batch that ``apply --stage`` or the MCP server left waiting."""
    workspace = Workspace.open(args.registry)
    pending = Pending.load(workspace.root)
    if pending is None or not pending.jobs:
        _say("  nothing is staged")
        return 1

    _rule("Staged")
    _say(render_pending(pending))

    decisions: dict[str, bool] = {}
    if args.all:
        decisions = {c.change_id: True for job in pending.jobs for c in job.changes}
        _say("\n  --all: approving every staged change.")
    elif args.change:
        wanted = set(args.change)
        decisions = {
            c.change_id: c.change_id in wanted for job in pending.jobs for c in job.changes
        }
    else:
        reviewer = _terminal_reviewer()
        for job in pending.jobs:
            for change in job.changes:
                decisions[change.change_id] = reviewer(change, job)

    with workspace.client(max_operations=args.max_operations) as client:
        report = commit(
            client,
            pending,
            workspace.state,
            decisions=decisions,
            write_back=not args.no_write_back,
            force_write=args.force_write,
            on_progress=(lambda who, msg: _say(f"    {who}: {msg}")) if args.verbose else None,
        )
    _rule("Result")
    _say(render_report(report))
    pending.clear()
    if report.ok:
        workspace.advance_baseline()
    return 0 if report.ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    from docsync.mcp import serve

    return serve(registry_path=args.registry, max_operations=args.max_operations)


# ---------------------------------------------------------------------------


def _auto_approve(_change: PendingChange, _job: PendingJob) -> bool:
    """Named so that it reads as a decision somebody made, in a script."""
    return True


def _terminal_reviewer():
    def review(change: PendingChange, job: PendingJob) -> bool:
        print(f"\n  ── {job.path} · {change.operation}")
        if change.explanation:
            print(f"     why:    {change.explanation}")
        if change.old_text:
            print(f"     before: {_clip(change.old_text)}")
        print(f"     after:  {_clip(change.new_text)}")
        try:
            answer = input("     apply this change? [Y/n] ").strip().lower()
        except EOFError:
            print("     → no decision available on a closed stdin; treating as no")
            return False
        return answer in {"", "y", "yes"}

    return review


def _clip(text: str, width: int = 150) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _report_quota(client) -> None:
    """What the account can actually spend, from both pools.

    The first version of this read `monthly_used` and `monthly_limit` off the
    top level of the whoami response. Neither key exists — the quota is nested
    — so the line silently never printed. A budget display that fails closed
    and says nothing is exactly as useful as no budget display, and it took a
    live run to notice, which is the argument for making one.
    """
    try:
        total, breakdown = client.remaining_operations()
        if total is not None:
            _say(f"  account: {total} operation(s) available — {breakdown}")
    except SuperDocsError:
        pass  # informational only; never block a run on it


# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        "docsync",
        description="Keep specs, ADRs and runbooks in step with the code they describe.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--registry",
            default=".",
            help="the docsync.yaml, or a directory holding one (default: the current directory)",
        )

    def baseline(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--base", default="", help="compare against a git revision, e.g. main")
        sp.add_argument("--base-dir", default="", help="compare against another directory")
        sp.add_argument(
            "--allow-prose",
            action="store_true",
            help="also edit documents where the old value does not appear literally. "
            "These edits cannot be verified afterwards and are reported as such.",
        )
        sp.add_argument("--show-instruction", nargs="?", const="*", default="",
                        help="print the exact message that would be sent (all, or one path)")

    def spending(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--max-operations", type=int, default=40,
                        help="hard stopping rule: refuse to spend more than this")
        sp.add_argument("--no-write-back", action="store_true",
                        help="edit the SuperDocs copy but leave the files on disk alone")
        sp.add_argument("--force-write", action="store_true",
                        help="write back over a file that has uncommitted changes")

    f = sub.add_parser("facts", help="print what the code currently says (offline, free)")
    common(f)
    f.add_argument("--json", action="store_true")
    f.set_defaults(fn=cmd_facts)

    a = sub.add_parser("audit", help="check every coverage claim against the documents (offline)")
    common(a)
    a.set_defaults(fn=cmd_audit)

    pl = sub.add_parser("plan", help="what has drifted and what it would cost (offline, free)")
    common(pl)
    baseline(pl)
    pl.set_defaults(fn=cmd_plan)

    sn = sub.add_parser("snapshot", help="record the current values as the baseline")
    common(sn)
    sn.set_defaults(fn=cmd_snapshot)

    ap = sub.add_parser("apply", help="propagate the drift into the documents, with a human gate")
    common(ap)
    baseline(ap)
    spending(ap)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan and its cost without making a billable call")
    ap.add_argument("--yes", action="store_true",
                    help="approve every proposed change without reading it")
    ap.add_argument("--model-tier", default="pro", choices=["core", "turbo", "pro", "max"])
    ap.set_defaults(fn=cmd_apply)

    apr = sub.add_parser("approve", help="decide a batch staged earlier (by the MCP server)")
    common(apr)
    spending(apr)
    apr.add_argument("--all", action="store_true", help="approve every staged change")
    apr.add_argument("--change", action="append", help="approve only these change ids")
    apr.set_defaults(fn=cmd_approve, dry_run=False)

    sv = sub.add_parser("serve", help="run as an MCP server over stdio")
    common(sv)
    sv.add_argument("--max-operations", type=int, default=40)
    sv.set_defaults(fn=cmd_serve)

    return p


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)-5s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        return int(args.fn(args))
    except (RegistryError, SourceError, StateError, SuperDocsError) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted — nothing further was sent", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
