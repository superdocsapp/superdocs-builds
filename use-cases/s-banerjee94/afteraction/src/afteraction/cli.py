"""`afteraction` — the command line.

    afteraction demo                  both storms, offline, showing the carry-forward
    afteraction build storm-a --live  the real thing, against the SuperDocs API
    afteraction lessons               what is open, what is closed, and since when
    afteraction verify storm-a        parse and check the records without drafting

The default everywhere is offline. Running against the live API costs operations and
is opt-in, because a tool that spends money by default is a tool that spends money by
accident.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import textwrap
from pathlib import Path

import typer

# A Windows console defaults to cp1252, which cannot encode the typographic quotes and
# dashes that appear in the report's own text — printing a proposed change would raise
# UnicodeEncodeError mid-review. Reconfiguring the streams fixes the whole class rather
# than the one character that happened to surface it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # already wrapped, or not a real console
        pass

from .client import ProposedChange, SuperDocsClient
from .corpus import available_events, load_corpus
from .facts import SECTION_TITLES, build_facts
from .lessons import DEFAULT_STORE, load_store
from .mock import MockSuperDocs
from .models import Kind, LessonStatus
from .pipeline import run_event

app = typer.Typer(add_completion=False, help=__doc__)

OK = typer.style("ok", fg=typer.colors.GREEN, bold=True)
BAD = typer.style("FAIL", fg=typer.colors.RED, bold=True)


def _echo(stage: str, detail: str) -> None:
    typer.echo(f"  {typer.style(f'{stage:<8}', fg=typer.colors.CYAN)} {detail}")


def _load_key() -> str:
    """Read the key from the environment, falling back to a local .env.

    Never printed, never logged, never passed on a command line.
    """
    key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    if key:
        return key
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SUPERDOCS_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise typer.BadParameter(
        "no API key found. Copy .env.example to .env and set SUPERDOCS_API_KEY, "
        "or run without --live to use the offline mock."
    )


def _readable(html: str | None) -> str:
    """HTML as prose a person can actually read at a terminal."""
    if not html:
        return "(nothing)"
    text = re.sub(r"<img[^>]*alt=\"([^\"]*)\"[^>]*>", r"[image: \1]", html)
    text = re.sub(r"</(p|tr|h[1-3])>", "\n", text)
    text = re.sub(r"</t[dh]>", " | ", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def _show(label: str, html: str | None, colour: str, width: int) -> None:
    typer.echo(typer.style(f"    {label}", fg=colour, bold=True))
    for block in _readable(html).splitlines():
        for line in textwrap.wrap(block, width=width) or [""]:
            typer.echo(f"      {line}")


def _interactive_gate(change: ProposedChange) -> tuple[bool, str | None]:
    """The human gate, at a terminal. Rejection is a first-class outcome.

    The whole proposed text is shown, never a truncated prefix: a reviewer asked to
    approve a change they cannot fully see is not a gate, and an edit hiding past the
    cut-off is exactly the one worth catching.
    """
    width = max(60, min(shutil.get_terminal_size((100, 24)).columns - 8, 110))
    typer.echo()
    typer.echo(typer.style("  " + "-" * (width - 2), fg=typer.colors.BRIGHT_BLACK))
    typer.echo(typer.style(f"  proposed {change.operation}: {change.explanation}", bold=True))
    if change.chunk_id:
        typer.echo(typer.style(f"  section chunk {change.chunk_id}", fg=typer.colors.BRIGHT_BLACK))
    typer.echo()
    _show("BEFORE", change.old_html, typer.colors.YELLOW, width)
    typer.echo()
    _show("AFTER", change.new_html, typer.colors.GREEN, width)
    typer.echo()

    if typer.confirm("    approve this change?", default=True):
        return True, None
    reason = typer.prompt("    reason (sent back to the model)", default="not supported by the records")
    return False, reason


def _gate_for(name: str):
    if name == "interactive":
        return _interactive_gate
    if name == "reject-all":
        return lambda change: (False, "rejected by policy for this run")
    return lambda change: (True, None)


def _report(result) -> None:
    trace = result.trace
    verdict = OK if result.ok else BAD
    typer.echo()
    typer.echo(f"  {verdict}  {trace.summary()}")
    for flagged in trace.flagged[:8]:
        typer.echo(
            typer.style(f"    [{flagged.verdict}] ", fg=typer.colors.RED)
            + f"({flagged.section}) {flagged.sentence[:110]}"
        )
    for problem in result.drift[:8]:
        typer.echo(typer.style("    [drift] ", fg=typer.colors.RED) + problem)
    if result.retried:
        typer.echo(
            typer.style(
                f"  re-issued after an edit did not land: {', '.join(result.retried)}",
                fg=typer.colors.YELLOW,
            )
        )
    typer.echo(
        f"  carried forward: {result.carry['inherited']} inherited "
        f"({result.carry['inherited_open']} open, {result.carry['inherited_closed']} closed), "
        f"{result.carry['raised_here']} raised here"
    )
    if result.skipped:
        typer.echo(
            typer.style(
                f"  {len(result.skipped)} sections not drafted (--limit): "
                f"{', '.join(result.skipped)}",
                fg=typer.colors.YELLOW,
            )
        )
    cost = "not billed (offline)" if result.operations is None else f"{result.operations} operations"
    typer.echo(f"  {result.edits} edit turns, {result.seconds:.1f}s, {cost}")
    for kind, path in result.exports.items():
        typer.echo(f"  exported {kind}: {path}")


@app.command()
def build(
    event: str = typer.Argument(..., help="event id, e.g. storm-a"),
    live: bool = typer.Option(False, "--live", help="use the real SuperDocs API (costs operations)"),
    gate: str = typer.Option("approve-all", help="approve-all | interactive | reject-all"),
    limit: int | None = typer.Option(None, "--limit", help="cap billable edit turns (small-sample mode)"),
    model_tier: str = typer.Option("core", help="core | turbo | pro | max"),
    store: Path = typer.Option(DEFAULT_STORE, help="carry-forward store"),
    out: Path | None = typer.Option(None, help="output directory"),
) -> None:
    """Draft one event's after-action report inside a SuperDocs document."""
    backend = SuperDocsClient(_load_key()) if live else MockSuperDocs()
    where = "live SuperDocs API" if live else "offline mock"
    typer.echo(typer.style(f"\n{event} — building against the {where}\n", bold=True))
    try:
        result = run_event(
            event,
            backend,
            store_path=store,
            out_dir=out or Path("out") / event,
            approver=_gate_for(gate),
            sections_limit=limit,
            model_tier=model_tier,
            on_event=_echo,
        )
    finally:
        backend.close()
    _report(result)
    raise typer.Exit(0 if result.ok else 1)


@app.command()
def demo(
    live: bool = typer.Option(False, "--live", help="use the real SuperDocs API (costs operations)"),
    store: Path = typer.Option(Path("out") / "demo-lessons.json", help="carry-forward store"),
) -> None:
    """Run both storms in order, so the carry-forward can be seen working.

    Storm B opens Storm A's lessons as open or closed because it read them from the
    store, not because they were typed in again.
    """
    if store.exists():
        store.unlink()
    failures = 0
    for event in ("storm-a", "storm-b"):
        backend = SuperDocsClient(_load_key()) if live else MockSuperDocs()
        typer.echo(typer.style(f"\n=== {event} ===\n", bold=True))
        try:
            result = run_event(
                event,
                backend,
                store_path=store,
                out_dir=Path("out") / event,
                on_event=_echo,
            )
        finally:
            backend.close()
        _report(result)
        failures += 0 if result.ok else 1
    typer.echo()
    lessons(store=store)
    raise typer.Exit(1 if failures else 0)


@app.command()
def lessons(store: Path = typer.Option(DEFAULT_STORE, help="carry-forward store")) -> None:
    """Show the carry-forward store: what is open, what is closed, and where."""
    items = load_store(store)
    if not items:
        typer.echo(f"no lessons recorded yet ({store})")
        return
    typer.echo(typer.style(f"\nlessons-learned register — {store}\n", bold=True))
    for item in items:
        if item.status is LessonStatus.CLOSED:
            mark = typer.style("closed", fg=typer.colors.GREEN)
            trail = f"closed in {item.closed_in_event}: {item.closed_note}"
        else:
            mark = typer.style("open  ", fg=typer.colors.YELLOW)
            trail = item.carry_note or item.detail
        typer.echo(f"  {mark}  {item.lesson_id}  {item.title}")
        typer.echo(f"          raised in {item.opened_in_event} · owner {item.owner}")
        typer.echo(f"          {trail[:130]}")
        typer.echo()


@app.command()
def verify(event: str = typer.Argument(..., help="event id, e.g. storm-a")) -> None:
    """Parse the records and show what they support, without drafting anything."""
    facts = build_facts(load_corpus(event))
    ev = facts.corpus.event
    typer.echo(typer.style(f"\n{ev.name} — {ev.utility}\n", bold=True))
    typer.echo(
        f"  {len(facts.corpus.log)} log entries · {len(facts.corpus.crews)} crews · "
        f"{len(facts.corpus.comms)} communications · {len(facts.readings)} consumer counts"
    )
    for key, title in SECTION_TITLES.items():
        claims = facts.for_section(key)
        observed = sum(1 for c in claims if c.kind is Kind.OBSERVED)
        assessed = sum(1 for c in claims if c.kind is Kind.ASSESSED)
        gaps = len(facts.gaps_for(key))
        typer.echo(f"\n  {typer.style(title, bold=True)}: {observed} observed, {assessed} assessed, {gaps} gaps")
        for claim in claims:
            tag = "OBS" if claim.kind is Kind.OBSERVED else "ASS"
            typer.echo(f"    [{tag}] {claim.rendered()[:140]}")
        for gap in facts.gaps_for(key):
            typer.echo(typer.style(f"    [GAP] {gap.detail[:140]}", fg=typer.colors.YELLOW))
    typer.echo()


@app.command()
def events() -> None:
    """List the events with data on disk."""
    for event in available_events():
        corpus = load_corpus(event)
        typer.echo(f"  {event:10} {corpus.event.name} ({len(corpus.log)} log entries)")


if __name__ == "__main__":
    app()
