"""The command line.

`check` never writes. `fix` writes only what a human approved. `apply` is the same gate with a
different front door, so another program can drive the whole flow without touching the interface.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .apply import apply_to_results
from .cache import VerdictCache
from .config import CONFIG_FILENAME, Config, ConfigError, load_config
from .model import Decision, Decisions, FileResult, Severity
from .reporters import render_json, render_sarif, render_terminal
from .runner import Event, Runner
from .state import RunStore, Stage, write_atomic
from .superdocs.client import SuperDocsClient
from .superdocs.errors import SuperDocsAuthError, SuperDocsError
from .targets import GitUnavailable, select_targets

app = typer.Typer(
    name="docs-lint",
    help="A house-style gate for Markdown documents. Checks changed docs against your style guide.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()
err = Console(stderr=True)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_UNCHECKED = 2
EXIT_MISUSE = 3


def _load(root: Path | None) -> Config:
    try:
        return load_config(root or Path.cwd())
    except ConfigError as exc:
        err.print(f"[bold red]Configuration error:[/] {exc}")
        raise typer.Exit(EXIT_MISUSE) from exc


def _client(config: Config, *, required: bool) -> SuperDocsClient | None:
    """Build a client, or explain clearly why the model pass will not run."""
    if not config.superdocs.enabled:
        return None
    if not os.environ.get("SUPERDOCS_API_KEY"):
        message = (
            "SUPERDOCS_API_KEY is not set, so the style-guide review cannot run. "
            "Local rules will still be checked."
        )
        if required:
            err.print(f"[bold red]{message}[/]")
            raise typer.Exit(EXIT_MISUSE)
        err.print(f"[yellow]{message}[/]")
        return None
    try:
        return SuperDocsClient()
    except SuperDocsAuthError as exc:
        err.print(f"[bold red]{exc}[/]")
        raise typer.Exit(EXIT_MISUSE) from exc


def _observer(verbose: bool):
    def observe(event: Event) -> None:
        if verbose:
            console.print(f"[dim]{event}[/dim]")

    return observe


def _select(config: Config, paths: list[str], since: str | None, sample: int):
    try:
        return select_targets(
            config, paths=paths, since=since, limit=sample or config.superdocs.sample
        )
    except GitUnavailable as exc:
        err.print(f"[bold red]{exc}[/]")
        raise typer.Exit(EXIT_MISUSE) from exc


def _emit(summary, config: Config, fmt: str, verbose: bool) -> None:
    if fmt == "json":
        console.print_json(render_json(summary, error_on=config.error_on))
    elif fmt == "sarif":
        print(render_sarif(summary, error_on=config.error_on))
    else:
        render_terminal(summary, error_on=config.error_on, console=console, show_timings=verbose)


# -- init ---------------------------------------------------------------------------


@app.command()
def init(
    styleguide: Annotated[
        Path | None, typer.Option("--styleguide", help="Path to your style guide Markdown file.")
    ] = None,
    root: Annotated[Path | None, typer.Option("--root", help="Repository root.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing config.")] = False,
) -> None:
    """Create docs-lint.toml and upload the style guide to SuperDocs.

    The guide is uploaded once and referenced by name thereafter, so swapping in a different house
    style is a file change rather than a code change.
    """
    base = (root or Path.cwd()).resolve()
    config_path = base / CONFIG_FILENAME
    if config_path.exists() and not force:
        err.print(f"[yellow]{config_path} already exists. Use --force to overwrite.[/]")
        raise typer.Exit(EXIT_MISUSE)

    guide = styleguide or Path("styleguide.md")
    guide_path = base / guide if not guide.is_absolute() else guide
    if not guide_path.is_file():
        err.print(
            f"[bold red]No style guide at {guide_path}.[/]\n"
            "Write one (a plain Markdown list of house rules is enough), then re-run:\n"
            f"  docs-lint init --styleguide {guide}"
        )
        raise typer.Exit(EXIT_MISUSE)

    import hashlib

    data = guide_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    relative = guide_path.relative_to(base).as_posix()

    attachment_id = ""
    if os.environ.get("SUPERDOCS_API_KEY"):
        try:
            with SuperDocsClient() as client:
                session = f"docs-lint-styleguide-{digest[:12]}"
                upload = client.upload_reference(guide_path.name, data, session_id=session)
                console.print("[dim]uploaded; waiting for it to become searchable...[/dim]")
                ready = client.wait_for_attachment(upload)
                attachment_id = ready.attachment_id
                console.print(f"[green]Style guide uploaded[/] ({ready.chunks_count} chunks)")
        except SuperDocsError as exc:
            err.print(f"[yellow]Could not upload the style guide: {exc}[/]")
            err.print("[yellow]Config written anyway; re-run init when SuperDocs is reachable.[/]")
    else:
        err.print("[yellow]SUPERDOCS_API_KEY not set; wrote config without uploading.[/]")

    write_atomic(config_path, _default_config(relative, digest, attachment_id))
    console.print(f"[green]Wrote {config_path}[/]")
    console.print("Next: [bold]docs-lint check[/]")


def _default_config(styleguide: str, digest: str, attachment_id: str) -> str:
    return f"""# docs-lint configuration.
# Everything here is data: severities, banned terms and the style guide itself.
# Changing any of it is a config edit, never a code change.

[docs-lint]
include = ["**/*.md", "**/*.mdx"]
exclude = ["**/node_modules/**", "**/.venv/**", "CHANGELOG.md"]
# Only these severities make the command exit non-zero.
error_on = ["error"]

[styleguide]
path = "{styleguide}"
attachment_id = "{attachment_id}"
# Edit the guide and this hash stops matching, which correctly invalidates every cached verdict.
content_sha256 = "{digest}"

[superdocs]
enabled = true
# Hard ceiling on billed operations per run. The run stops and says what it skipped.
budget_operations = 100
# Check at most this many files in one run; 0 means no limit.
sample = 0

[rules.banned-terms]
severity = "error"
terms = {{ utilise = "use", leverage = "use", "in order to" = "to" }}

[rules.heading-case]
severity = "warning"
proper_nouns = []

[rules.heading-punctuation]
severity = "warning"

[rules.fence-language]
severity = "warning"

[rules.long-sentence]
severity = "info"
max_words = 35

[rules.passive-voice]
severity = "off"

# Findings proposed by the style-guide review.
[rules.style-guide]
severity = "warning"

# Proposals that did not match any part of the document under review.
[rules.unanchored-proposal]
severity = "warning"
"""


# -- check --------------------------------------------------------------------------


@app.command()
def check(
    paths: Annotated[list[str] | None, typer.Argument(help="Files to check.")] = None,
    since: Annotated[
        str | None, typer.Option("--since", help="Only files changed since this git ref.")
    ] = None,
    fmt: Annotated[
        str, typer.Option("--format", help="Output format: terminal, json or sarif.")
    ] = "terminal",
    sample: Annotated[int, typer.Option("--sample", help="Check at most N files.")] = 0,
    no_ai: Annotated[bool, typer.Option("--no-ai", help="Local rules only.")] = False,
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Ignore cached verdicts.")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Show stages and cost.")] = False,
    root: Annotated[Path | None, typer.Option("--root", help="Repository root.")] = None,
) -> None:
    """Check documents. Never writes to anything.

    This is the pre-commit hook and the CI command. With no arguments it checks the configured
    globs; pre-commit passes staged files as arguments, and CI should pass --since.
    """
    config = _load(root)
    if no_ai:
        config = config.model_copy(
            update={"superdocs": config.superdocs.model_copy(update={"enabled": False})}
        )

    targets, notes = _select(config, paths or [], since, sample)
    if not targets:
        console.print("[dim]No Markdown documents to check.[/dim]")
        raise typer.Exit(EXIT_OK)

    runner = Runner(
        config=config,
        store=RunStore(config.root),
        cache=VerdictCache(
            config.root, config_fingerprint=config.fingerprint(), enabled=not no_cache
        ),
        client=_client(config, required=False),
        observe=_observer(verbose),
    )

    try:
        summary = runner.check(targets, notes=notes)
    except SuperDocsAuthError as exc:
        err.print(f"[bold red]{exc}[/]")
        raise typer.Exit(EXIT_UNCHECKED) from exc

    _emit(summary, config, fmt, verbose)
    raise typer.Exit(summary.exit_code(config.error_on))


# -- fix ----------------------------------------------------------------------------


@app.command()
def fix(
    paths: Annotated[list[str] | None, typer.Argument(help="Files to check and fix.")] = None,
    since: Annotated[
        str | None, typer.Option("--since", help="Only files changed since a ref.")
    ] = None,
    plan: Annotated[
        Path | None,
        typer.Option("--plan", help="Write a decisions file for review instead of opening the UI."),
    ] = None,
    no_ai: Annotated[bool, typer.Option("--no-ai", help="Local rules only.")] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Show stages and cost.")] = False,
    root: Annotated[Path | None, typer.Option("--root", help="Repository root.")] = None,
) -> None:
    """Propose corrections for human approval, and apply only what is approved.

    With --plan, writes a decisions file with every fix set to false. Edit it, then run
    `docs-lint apply`. Without it, opens the review interface.
    """
    config = _load(root)
    if no_ai:
        config = config.model_copy(
            update={"superdocs": config.superdocs.model_copy(update={"enabled": False})}
        )

    targets, notes = _select(config, paths or [], since, 0)
    if not targets:
        console.print("[dim]No Markdown documents to check.[/dim]")
        raise typer.Exit(EXIT_OK)

    store = RunStore(config.root)
    runner = Runner(
        config=config,
        store=store,
        cache=VerdictCache(config.root, config_fingerprint=config.fingerprint(), enabled=False),
        client=_client(config, required=False),
        observe=_observer(verbose),
    )
    summary = runner.check(targets, notes=notes)

    fixable = [f for f in summary.all_findings if f.is_fixable]
    if not fixable:
        _emit(summary, config, "terminal", verbose)
        console.print("[dim]Nothing here can be fixed automatically.[/dim]")
        raise typer.Exit(summary.exit_code(config.error_on))

    plan_path = plan or (store.run_dir(summary.run_id) / "decisions.json")
    write_atomic(plan_path, _decisions_template(summary))
    console.print()
    console.print(f"[bold]{len(fixable)} proposed fix(es).[/] Nothing has been applied.")
    console.print(
        f'Review them in [bold]{plan_path}[/], set "approved": true on the ones you want,'
    )
    console.print(f"then run: [bold]docs-lint apply {plan_path}[/]")
    raise typer.Exit(EXIT_OK)


def _decisions_template(summary) -> str:
    """A decisions file with everything rejected by default.

    Defaulting to false is the point: a reviewer who approves nothing, or who abandons the file
    halfway, changes no documents at all.
    """
    return json.dumps(
        {
            "run_id": summary.run_id,
            "_comment": "Set approved: true for each fix you want applied. Anything left false, "
            "or removed from this file, will not be applied.",
            "decisions": [
                {
                    "finding_id": finding.finding_id,
                    "approved": False,
                    "path": finding.anchor.path,
                    "line": finding.anchor.start_line,
                    "rule": finding.rule_id,
                    "message": finding.message,
                    "before": finding.original,
                    "after": finding.replacement,
                }
                for result in summary.results
                for finding in result.findings
                if finding.is_fixable
            ],
        },
        indent=2,
    )


# -- apply --------------------------------------------------------------------------


@app.command()
def apply(
    decisions_file: Annotated[Path, typer.Argument(help="A decisions file from `docs-lint fix`.")],
    root: Annotated[Path | None, typer.Option("--root", help="Repository root.")] = None,
) -> None:
    """Apply the fixes approved in a decisions file. The machine-drivable gate.

    Anything not explicitly approved is left alone, and anything that could not be applied is
    reported rather than glossed over.
    """
    config = _load(root)
    store = RunStore(config.root)

    try:
        raw = json.loads(decisions_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        err.print(f"[bold red]Could not read {decisions_file}: {exc}[/]")
        raise typer.Exit(EXIT_MISUSE) from exc

    run_id = raw.get("run_id")
    if not run_id:
        err.print("[bold red]That decisions file has no run_id.[/]")
        raise typer.Exit(EXIT_MISUSE)

    try:
        state = store.load(run_id)
    except FileNotFoundError as exc:
        err.print(f"[bold red]{exc}[/]")
        raise typer.Exit(EXIT_MISUSE) from exc

    decisions = Decisions(
        run_id=run_id,
        decisions=tuple(
            Decision(finding_id=item["finding_id"], approved=bool(item.get("approved", False)))
            for item in raw.get("decisions", [])
            if isinstance(item, dict) and item.get("finding_id")
        ),
    )

    results = [
        FileResult(
            path=f.path,
            verdict=f.verdict,
            findings=f.findings,
            ops_charged=f.ops_charged,
        )
        for f in state.files
        if f.verdict is not None
    ]

    client = _client(config, required=False)
    outcome = apply_to_results(
        results,
        decisions,
        root=config.root,
        client=client,
        sessions={f.path: f.session_id for f in state.files if f.session_id},
        job_ids={f.path: f.job_id for f in state.files if f.job_id},
    )

    for fixed in outcome.applied:
        console.print(f"[green]applied[/] {fixed.path}: {fixed.summary}")
    for skipped in outcome.skipped:
        console.print(
            f"[yellow]not applied[/] {skipped.path} ({skipped.rule_id}): {skipped.reason}"
        )

    if outcome.drift:
        console.print()
        console.print(
            "[bold yellow]Warning: the export changed text nobody approved.[/]\n"
            "[yellow]This is a SuperDocs export fidelity issue rather than an approved edit "
            "(see BUGS.md). Check these before committing:[/]"
        )
        for drift in outcome.drift:
            preview = drift.before if len(drift.before) <= 70 else drift.before[:70] + "…"
            console.print(
                f"[yellow]  {drift.path}: {preview!r} — {drift.after or 'no longer present'}[/]"
            )

    console.print()
    console.print(outcome.summary_line())
    raise typer.Exit(EXIT_OK if outcome.ok else EXIT_FINDINGS)


# -- resume and report --------------------------------------------------------------


@app.command()
def resume(
    run_id: Annotated[
        str | None, typer.Argument(help="Run to resume; defaults to the latest.")
    ] = None,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Show stages and cost.")] = False,
    root: Annotated[Path | None, typer.Option("--root", help="Repository root.")] = None,
) -> None:
    """Continue an interrupted run, without redoing or re-paying for finished work."""
    config = _load(root)
    store = RunStore(config.root)
    run_id = run_id or store.latest_run_id()
    if not run_id:
        err.print("[yellow]No previous run to resume.[/]")
        raise typer.Exit(EXIT_MISUSE)

    try:
        state = store.load(run_id)
    except FileNotFoundError as exc:
        err.print(f"[bold red]{exc}[/]")
        raise typer.Exit(EXIT_MISUSE) from exc

    targets, _ = select_targets(config, paths=[f.path for f in state.files])
    runner = Runner(
        config=config,
        store=store,
        cache=VerdictCache(config.root, config_fingerprint=config.fingerprint()),
        client=_client(config, required=False),
        observe=_observer(verbose),
    )
    try:
        summary = runner.resume(run_id, targets)
    except ConfigError as exc:
        err.print(f"[bold red]{exc}[/]")
        raise typer.Exit(EXIT_MISUSE) from exc

    _emit(summary, config, "terminal", verbose)
    raise typer.Exit(summary.exit_code(config.error_on))


@app.command()
def report(
    run_id: Annotated[
        str | None, typer.Argument(help="Run to report on; defaults to latest.")
    ] = None,
    root: Annotated[Path | None, typer.Option("--root", help="Repository root.")] = None,
) -> None:
    """Show what a run spent and where its time went."""
    config = _load(root)
    store = RunStore(config.root)
    run_id = run_id or store.latest_run_id()
    if not run_id:
        err.print("[yellow]No runs recorded yet.[/]")
        raise typer.Exit(EXIT_MISUSE)

    state = store.load(run_id)
    console.print(f"[bold]{state.run_id}[/]  ({state.mode}, started {state.created_at})")
    console.print(f"  documents        {len(state.files)}")
    console.print(f"  operations spent {state.ops_charged}")
    for stage, seconds in sorted(state.stage_seconds.items()):
        console.print(f"  {stage:<16} {seconds:.2f}s")
    if state.degraded:
        console.print("[yellow]  degraded:[/]")
        for note in state.degraded:
            console.print(f"[yellow]    - {note}[/]")

    awaiting = [f for f in state.files if f.stage is Stage.AWAITING_REVIEW]
    if awaiting:
        console.print(f"[bold]{len(awaiting)} document(s) still awaiting review[/]")


@app.command(name="rules")
def list_rules() -> None:
    """List the built-in rules and their default severities."""
    from .rules import all_rules

    for rule in all_rules():
        console.print(
            f"[magenta]{rule.rule_id:<22}[/] "
            f"[dim]{rule.default_severity.value:<8}[/] {rule.description}"
        )
    console.print(
        "\n[dim]Set severity per rule in docs-lint.toml under [rules.<id>]. "
        f"Valid severities: {', '.join(s.value for s in Severity)}.[/dim]"
    )


def main() -> None:  # pragma: no cover - console-script entry point
    try:
        app()
    except KeyboardInterrupt:
        err.print("\n[yellow]Interrupted. Nothing was written; resume with `docs-lint resume`.[/]")
        sys.exit(EXIT_MISUSE)


if __name__ == "__main__":  # pragma: no cover
    main()
