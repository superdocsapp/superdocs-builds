"""Terminal output.

Two things this format refuses to do: describe a partial run as if it were complete, and print a
green tick over files it never checked. The summary line therefore leads with what was checked, and
anything skipped, failed or degraded is stated before the good news rather than after it.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..model import RunSummary, Severity, Source, VerdictKind

SEVERITY_STYLE = {
    Severity.ERROR: "bold red",
    Severity.WARNING: "yellow",
    Severity.INFO: "cyan",
    Severity.OFF: "dim",
}

VERDICT_STYLE = {
    VerdictKind.CLEAN: "green",
    VerdictKind.FINDINGS: "yellow",
    VerdictKind.SKIPPED: "dim",
    VerdictKind.FAILED: "bold red",
}


def render_terminal(
    summary: RunSummary,
    *,
    error_on: frozenset[Severity],
    console: Console | None = None,
    show_timings: bool = False,
) -> None:
    console = console or Console()

    for result in summary.results:
        if not result.findings:
            continue
        console.print()
        console.print(Text(result.path, style="bold underline"))
        for finding in sorted(result.findings, key=lambda f: (f.anchor.start_line, f.rule_id)):
            _print_finding(console, finding)

    _print_unchecked(console, summary)
    _print_degraded(console, summary)

    if show_timings:
        _print_timings(console, summary)

    console.print()
    exit_code = summary.exit_code(error_on)
    style = "green" if exit_code == 0 else ("bold red" if exit_code == 2 else "yellow")
    console.print(Text(summary.headline(error_on), style=style))

    fixable = sum(1 for f in summary.all_findings if f.is_fixable)
    if fixable:
        console.print(
            Text(
                f"{fixable} of these can be fixed. Run `docs-lint fix` to review them one by one.",
                style="dim",
            )
        )


def _print_finding(console: Console, finding) -> None:
    style = SEVERITY_STYLE.get(finding.severity, "")
    origin = "ai" if finding.source is Source.SUPERDOCS else "rule"

    line = Text()
    line.append(f"  {finding.anchor.start_line:>4}  ", style="dim")
    line.append(f"{finding.severity.value:<8}", style=style)
    line.append(f"{finding.rule_id} ", style="magenta")
    line.append(f"({origin})  ", style="dim")
    line.append(finding.message)
    console.print(line)

    if finding.anchor.heading_path:
        console.print(Text(f"        in {finding.anchor.section}", style="dim"))
    if finding.explanation:
        console.print(Text(f"        {finding.explanation}", style="dim italic"))
    if finding.is_fixable and finding.original is not None:
        console.print(Text(f"        - {finding.original}", style="red"))
        console.print(Text(f"        + {finding.replacement}", style="green"))


def _print_unchecked(console: Console, summary: RunSummary) -> None:
    """Name every file that was not checked, and why. Never leave this implicit."""
    unchecked = [r for r in summary.results if not r.verdict.is_trustworthy]
    if not unchecked:
        return
    console.print()
    console.print(Text("Not checked:", style="bold"))
    for result in unchecked:
        style = VERDICT_STYLE.get(result.verdict.kind, "")
        reason = result.verdict.reason or "no reason recorded"
        console.print(Text(f"  {result.path}: {result.verdict.kind.value} — {reason}", style=style))


def _print_degraded(console: Console, summary: RunSummary) -> None:
    if not summary.degraded:
        return
    console.print()
    console.print(Text("This run was degraded:", style="bold yellow"))
    for note in summary.degraded:
        console.print(Text(f"  - {note}", style="yellow"))


def _print_timings(console: Console, summary: RunSummary) -> None:
    table = Table(title="Where the time and money went", title_style="bold", show_edge=False)
    table.add_column("stage")
    table.add_column("seconds", justify="right")
    for stage, seconds in sorted(summary.stage_seconds.items()):
        table.add_row(stage, f"{seconds:.2f}")
    table.add_row("operations charged", str(summary.ops_charged), style="bold")
    cached = sum(1 for r in summary.results if r.from_cache)
    table.add_row("answered from cache", f"{cached}/{len(summary.results)}", style="dim")
    console.print()
    console.print(table)
