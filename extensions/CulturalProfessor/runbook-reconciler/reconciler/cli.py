"""The command line.

Subcommands are registered in `COMMANDS` and land stage by stage; a command
appears here when it works, so `./rr --help` never advertises something that
answers "not implemented yet".

Every command that can spend a paid operation says so in its own help text, and
the one that can — `propose` — refuses to spend anything until it is asked
twice: run it and it prices the work, run it with `--yes` and it does it. The
default everywhere is that nothing spends.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Callable
from pathlib import Path

from reconciler import __version__
from reconciler.config import PROJECT_ROOT, Config
from reconciler.confluence import PageSource, describe_source, page_source
from reconciler.register import Register
from reconciler.sweep import Sweep, SweepResult

Handler = Callable[[argparse.Namespace], int]


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"runbook-reconciler {__version__}")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    """The free layer, end to end. No model, no spend.

    Not necessarily no network: with Confluence configured this reads the live
    site, which is why it says which one it read before it says what it found.
    An output that does not name its own inputs is how somebody spends an
    afternoon debugging a finding about a page they were not looking at.
    """
    config = _configure(args)
    source = page_source(config)
    print(f"reading {describe_source(source)}\n")
    with Register(config.register_path) as register:
        result = Sweep(config, register, source=source).run(mode="check")
        _report(result, verbose=args.verbose)
    _close(source)
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
    """Score the checker against the key that was written before it.

    Deliberately the one command that does not call `page_source`: the key is
    the corpus's planted drift, so scoring against whatever Confluence site
    happens to be configured would produce a precision number about somebody
    else's wiki and report it as this project's.
    """
    from reconciler.measure import score, write_raw

    config = Config.load()
    with Register(config.register_path) as register:
        result = Sweep(config, register).run(mode="measure")

    scored = score(result.findings, result.claims)
    for line in scored.lines():
        print(line)

    # Scored second and printed separately, never folded in. Precision on
    # planted drift says how well the checker finds what is there; the negative
    # corpus says what it invents on prose that has nothing wrong with it, and
    # only the second predicts whether a team leaves it switched on.
    negative = _measure_negative(config)
    if negative is not None:
        print()
        for line in negative.lines():
            print(line)

    path = write_raw(scored, result.findings, negative=negative)
    print(f"\nraw data: {path}")
    failed = bool(scored.misses or scored.false_positives)
    failed = failed or bool(negative and negative.false_positives)
    return 0 if not failed else 1


def _measure_negative(config: Config):
    """Sweep `fixtures/negative/` — runbooks that are true — into a score.

    Deliberately not routed through `Sweep`: this must not touch the register.
    A corpus swept for measurement would put its claims and findings in the same
    store the review queue reads, and a reviewer would be shown findings about
    pages that exist only to prove the checker stays quiet.
    """
    from reconciler.check.vertical import check_page, load_checks
    from reconciler.confluence.local import LocalSource
    from reconciler.estate import Estate
    from reconciler.extract.patterns import extract_claims
    from reconciler.measure import score_negative

    directory = PROJECT_ROOT / "fixtures" / "negative"
    if not directory.is_dir():
        return None

    estate = Estate.load(config)
    checks = load_checks(config.checks_path)
    source = LocalSource(directory)
    by_page = {}
    for ref in source.pages():
        document = source.read(ref.page_id)
        by_page[ref.page_id] = check_page(ref.page_id, extract_claims(document), estate, checks)
    return score_negative(by_page)


def _cmd_propose(args: argparse.Namespace) -> int:
    """The only command that can spend, and it asks twice before it does.

    Priced first, spent second. The estimate is exact rather than indicative —
    one operation per page holding editable, undecided contradictions — because
    a tool that says "this may incur charges" has told the operator nothing they
    can act on.
    """
    from reconciler.edit import propose_all
    from reconciler.superdocs import SuperDocs

    config = Config.load()
    with Register(config.register_path) as register:
        pages = _pages_awaiting_proposal(register)
        if not pages:
            print("nothing to propose: no undecided contradictions are waiting for wording.")
            print("run `rr check` first, or `rr review` if they already have proposals.")
            return 0

        print(f"{sum(pages.values())} finding(s) across {len(pages)} page(s):")
        for page_id, count in sorted(pages.items()):
            print(f"  page {page_id}: {count} finding(s) → 1 operation")
        print(f"\nthis will spend {len(pages)} operation(s).")

        if not args.yes:
            print("nothing spent. re-run with --yes to go ahead.")
            return 0
        if not config.has_superdocs:
            print(
                "SUPERDOCS_API_KEY is not set — nothing spent. See .env.example.", file=sys.stderr
            )
            return 2

        with SuperDocs(api_key=config.superdocs_key) as client:
            spent = propose_all(register, client, model_tier=args.tier)
        print(
            f"\n{spent['operations']} operation(s) spent across {spent['pages']} page(s). "
            f"{spent['worded']} of {spent['requested']} finding(s) came back with usable wording."
        )
        # The wording layer is the one non-deterministic thing here, and saying
        # so at the moment it under-delivers beats a limitations section nobody
        # reads. Re-running retries only what still lacks wording.
        if spent["worded"] < spent["requested"]:
            missing = spent["requested"] - spent["worded"]
            print(
                f"{missing} still have none — either the wording was refused as unsafe or "
                f"the service declined it. Re-running `rr propose --yes` retries only those."
            )
        print("`rr review` is the next step; nothing has been written to any document yet.")
    return 0


def _pages_awaiting_proposal(register: Register) -> dict[str, int]:
    """Pages whose findings still need wording, counted the way they are billed.

    A finding whose passage this tool refuses to edit is deliberately absent: it
    resolves to a comment for a human, and paying a model to word a comment
    nobody asked for is exactly the spend rule 5 is about.
    """
    pages: dict[str, int] = {}
    for finding in register.review_queue():
        if finding.proposed or not finding.page_id:
            continue
        claim = register.claim(finding.claim_id or "")
        if claim is None or not claim.anchor.editable:
            continue
        pages[finding.page_id] = pages.get(finding.page_id, 0) + 1
    return pages


def _cmd_review(args: argparse.Namespace) -> int:
    """The gate. Reads decisions, writes only what was approved."""
    from reconciler.review import ReviewQueue, run_terminal_review

    config = _configure(args)
    source = page_source(config)
    print(f"reviewing against {describe_source(source)}\n")
    with Register(config.register_path) as register:
        result = run_terminal_review(ReviewQueue(register), source, auto=args.auto)
    _close(source)
    return 0 if result.ok else 1


def _cmd_sweep(args: argparse.Namespace) -> int:
    """Check, then review what it found. The whole loop, in the honest order.

    Proposing is not folded in here even with `--yes`, and that is deliberate:
    the one command that spends money should be the one command somebody typed
    on purpose. `rr sweep` tells you what it would cost and stops.
    """
    from reconciler.review import ReviewQueue, run_terminal_review

    config = _configure(args)
    source = page_source(config)
    print(f"sweeping {describe_source(source)}\n")
    try:
        with Register(config.register_path) as register:
            result = Sweep(config, register, source=source).run(
                mode="sweep", page_ids=args.pages or None
            )
            _report(result, verbose=args.verbose)

            if not args.review:
                pages = _pages_awaiting_proposal(register)
                if pages:
                    print(
                        f"\n{len(pages)} page(s) need wording before they can be reviewed: "
                        f"`rr propose` prices it."
                    )
                return 0 if not result.contradictions else 1

            print()
            outcome = run_terminal_review(ReviewQueue(register), source, auto=args.auto)
    finally:
        # The early return above is why this is a `finally` and not a call at
        # the end: the live adapter holds an httpx connection pool.
        _close(source)
    return 0 if outcome.ok else 1


def _cmd_watch(args: argparse.Namespace) -> int:
    """Sweep whenever the estate changes. Free: it never proposes on its own.

    Deliberately does not spend. A watcher that could open a paid session on a
    file save is a watcher that bills somebody for a rebase, so this reports and
    stops — `rr propose` is still a thing a person types.
    """
    from reconciler.watch import Watcher

    config = _configure(args)
    source = page_source(config)
    print(f"watching against {describe_source(source)}")
    try:
        with Register(config.register_path) as register:
            Watcher(
                config,
                register,
                source,
                interval=args.interval,
                quiet=args.quiet,
            ).loop()
    finally:
        _close(source)
    return 0


def _cmd_pack(args: argparse.Namespace) -> int:
    """Half two: the readiness report and the DR evidence document.

    Free. Both documents are built from the register offline, and `--export`
    sends them through SuperDocs' renderer and house template — upload and
    export are both free operations, which is why the pack leans on them
    instead of carrying a PDF library.
    """
    from reconciler.estate import Estate
    from reconciler.pack import build_dr_evidence, build_readiness, export_pack

    config = _configure(args)
    source = page_source(config)
    out = Path(args.out)
    try:
        with Register(config.register_path) as register:
            if not register.summary()["claims"]:
                print("the register is empty — run `rr check` first.", file=sys.stderr)
                return 2

            estate = Estate.load(config)
            coverage = Sweep(config, register, source=source).run(mode="pack").coverage
            packs = {
                "on-call-readiness": build_readiness(register, estate, coverage),
                "dr-evidence": build_dr_evidence(register, estate),
            }
    finally:
        _close(source)

    for name, pack in packs.items():
        path = pack.write(out, name)
        print(f"{pack.title}: {path}")
        if pack.divergences:
            print(f"  {len(pack.divergences)} subject(s) documented inconsistently across pages")

    if args.export:
        if not config.has_superdocs:
            print("SUPERDOCS_API_KEY is not set — the HTML above is still complete.")
            return 2
        from reconciler.superdocs import SuperDocs

        with SuperDocs(api_key=config.superdocs_key) as client:
            for name, pack in packs.items():
                blob = export_pack(client, pack, fmt=args.export)
                path = out / f"{name}.{args.export}"
                path.write_bytes(blob)
                print(f"exported {path} ({len(blob)} bytes, 0 paid operations)")
    return 0


def _cmd_mcp(_: argparse.Namespace) -> int:
    """Serve the four tools over stdio. Nothing but JSON-RPC on stdout."""
    from reconciler.mcp_server import serve

    return serve()


def _cmd_status(_: argparse.Namespace) -> int:
    """What the register holds, including the things that go wrong quietly."""
    config = Config.load()
    with Register(config.register_path) as register:
        summary = register.summary()
        print(f"register: {config.register_path}")
        print(
            f"  {summary['claims']} claims · {summary['agrees']} agree · "
            f"{summary['contradicts']} contradict · {summary['unverifiable']} unverifiable"
        )
        print(
            f"  {summary['awaiting_review']} awaiting review · "
            f"{summary['approved_unapplied']} approved and not yet written"
        )

        batches = register.open_batches()
        if batches:
            # A parked turn holds its session, and every later turn against it
            # comes back 409. Silence here is how that gets found a week later.
            print(f"\n{len(batches)} SuperDocs turn(s) still parked awaiting a decision:")
            for batch in batches:
                print(
                    f"  page {batch['page_id']} · job {batch['job_id']} · "
                    f"{batch['changes']} change(s) · opened {batch['opened']}"
                )

        rules = [r for r in register.decisions_by_rule() if r["approved"] or r["rejected"]]
        if rules:
            # A rejection is recorded against one finding, which is right. But a
            # rule that is wrong in general keeps firing on every other page and
            # nothing adds it up, so nobody notices the rule is the problem --
            # they notice the queue is not worth reading. This is the tally.
            print("\nhow each rule is doing in review:")
            for rule in rules:
                flag = "  ← worth a look" if rule["rejection_rate"] >= 0.5 else ""
                print(
                    f"  {rule['rule_id']:24} {rule['approved']} approved · "
                    f"{rule['rejected']} rejected · {rule['undecided']} undecided{flag}"
                )
            if any(r["rejection_rate"] >= 0.5 for r in rules):
                print("  a rule rejected more often than not is either wrong or not wanted here.")
                print("  `rr mute <finding-id>` writes one claim into config/mappings.yaml.")

        runs = register.last_runs(limit=5)
        if runs:
            print("\nrecent runs:")
            for run in runs:
                cost = register.run_cost(run["run_id"])
                print(
                    f"  {run['started_at']} · {run['mode']:8} · {run['status'] or 'running':9} · "
                    f"{cost['seconds']:.2f}s · {cost['operations']} operation(s)"
                )
    return 0


def _cmd_mute(args: argparse.Namespace) -> int:
    """Stop checking one claim, by writing it into config where it is visible.

    The escape hatch that keeps this installable has existed since the first
    stage and has never had a way to reach it: `ignore_subjects` is read on
    every sweep and the only way to add to it was to open the YAML. So the
    honest response to a false positive — "this claim is not worth checking" —
    was a decision a reviewer could make and not record, and the rule went on
    firing on every other page.

    Takes a finding id, because that is what `rr review` and `rr status` put in
    front of somebody, and mutes the *subject* behind it, because that is the
    thing that will come back. The distinction is worth being explicit about:
    muting is not rejecting. A rejection says "this sentence should not change";
    a mute says "stop asking about this claim at all", and it is written into a
    file somebody can read, review and revert.
    """
    from reconciler.config import mute_subject

    config = Config.load()
    with Register(config.register_path) as register:
        finding = register.finding(args.finding_id)
        if finding is None:
            print(f"no finding with id {args.finding_id!r}. `rr status` lists what is here.")
            return 2
        subject = finding.subject

        muted = mute_subject(subject)
        if muted:
            # Clearing the queue is half the job and the half that is easy to
            # forget. Muting only changes what *future* sweeps produce: the rows
            # already in the register keep their ids, keep `decision IS NULL`,
            # and sit in the review queue for ever, so the reviewer who just
            # said "stop asking me this" gets asked it again every time they
            # open the queue.
            #
            # Recorded as rejected rather than deleted. It is true — a human
            # declined to act on it — and it is what makes the per-rule tally in
            # `rr status` mean anything: a rule muted across four pages should
            # show as four rejections, which is exactly the signal that the rule
            # rather than the pages is the problem.
            cleared = [
                f for f in register.review_queue() if f.subject == subject and f.decision is None
            ]
            for stale in cleared:
                register.decide(stale.finding_id, "rejected")

    if muted:
        print(f"muted {subject!r} in config/mappings.yaml.")
        print("it will be reported unverifiable from the next sweep, never as correct.")
        if cleared:
            where = ", ".join(sorted({f.page_id or "estate" for f in cleared}))
            print(f"{len(cleared)} open finding(s) cleared from the review queue (page {where}).")
        print("delete the line to start checking it again.")
        return 0

    if subject in Config.load().mappings.ignore_subjects:
        print(f"{subject!r} is already muted in config/mappings.yaml.")
        return 0

    # The file is not in either shape this knows how to edit. Say what to add
    # rather than guessing at somebody's YAML.
    print("could not edit config/mappings.yaml automatically. Add this by hand:")
    print(f"\nignore_subjects:\n  - {subject!r}")
    return 1


def _close(source: PageSource) -> None:
    """The live adapter holds an httpx client; the corpus holds nothing."""
    closer = getattr(source, "close", None)
    if callable(closer):
        closer()


def _configure(args: argparse.Namespace) -> Config:
    """Config, plus the one thing a flag is allowed to override.

    `--corpus` is worth a flag rather than only an environment variable because
    it is what the demo types: it guarantees the offline half of the recording
    stays offline with real credentials sitting in `.env`.
    """
    config = Config.load()
    if getattr(args, "corpus", False):
        return dataclasses.replace(config, source_mode="corpus")
    return config


COMMANDS: dict[str, tuple[str, Handler]] = {
    "check": (
        "check every runbook against the estate (free: no model, no network, no spend)",
        _cmd_check,
    ),
    "sweep": (
        "check, and then optionally review what it found (free unless you review)",
        _cmd_sweep,
    ),
    "propose": (
        "ask SuperDocs to word the fixes — THE ONLY COMMAND THAT SPENDS, and not without --yes",
        _cmd_propose,
    ),
    "review": ("decide finding by finding, then write only what was approved", _cmd_review),
    "watch": ("sweep whenever the estate changes, debounced and coalesced (free)", _cmd_watch),
    "pack": ("build the on-call readiness and DR evidence documents (free)", _cmd_pack),
    "mcp": ("serve analyze/propose/approve/apply to an agent over stdio", _cmd_mcp),
    "status": ("what the register holds, and what is parked (free)", _cmd_status),
    "mute": ("stop checking the claim behind a finding, by writing it into config", _cmd_mute),
    "measure": ("score the checker against fixtures/expected.yaml", _cmd_measure),
    "version": ("print the version and exit", _cmd_version),
}

_VERBOSE = (
    ("--verbose", "-v"),
    {"action": "store_true", "help": "also list what could not be checked"},
)
_AUTO = (
    ("--auto",),
    {
        "choices": ["approve", "reject"],
        "help": "decide every finding the same way, without a terminal (for CI)",
    },
)
_CORPUS = (
    ("--corpus",),
    {
        "action": "store_true",
        "help": "read the bundled corpus even if Confluence is configured",
    },
)

_OPTIONS: dict[str, list[tuple[tuple[str, ...], dict]]] = {
    "check": [
        _VERBOSE,
        _CORPUS,
        (
            ("--exit-zero",),
            {"action": "store_true", "help": "always exit 0, for a non-blocking pre-commit hook"},
        ),
    ],
    "sweep": [
        _VERBOSE,
        _CORPUS,
        _AUTO,
        (
            ("--pages",),
            {
                "nargs": "+",
                "metavar": "ID",
                "help": "narrow to these page ids (coverage is then not computed)",
            },
        ),
        (
            ("--review",),
            {"action": "store_true", "help": "go straight into the review queue afterwards"},
        ),
    ],
    "review": [_AUTO, _CORPUS],
    "mute": [
        (
            ("finding_id",),
            {"help": "the finding whose subject should stop being checked"},
        ),
    ],
    "pack": [
        _CORPUS,
        (("--out",), {"default": "out", "help": "where to write the documents (default: out/)"}),
        (
            ("--export",),
            {
                "choices": ["pdf", "docx"],
                "help": "also render through SuperDocs' template (free, needs a key)",
            },
        ),
    ],
    "watch": [
        _CORPUS,
        (
            ("--interval",),
            {"type": float, "default": 10.0, "help": "seconds between polls (default: 10)"},
        ),
        (
            ("--quiet",),
            {
                "type": float,
                "default": 2.0,
                "help": "seconds everything must hold still before sweeping (default: 2)",
            },
        ),
    ],
    "propose": [
        (
            ("--yes",),
            {"action": "store_true", "help": "actually spend the operations priced above"},
        ),
        (
            ("--tier",),
            {"help": "SuperDocs model tier, if you want something other than the default"},
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
