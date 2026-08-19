"""Command line entry point."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from thread_resolver.adapters.cli_review import CliReviewGate, ReviewAborted
from thread_resolver.adapters.docx_source import DocxThreadSource, UnsupportedDocument
from thread_resolver.adapters.docx_writer import WriteBackError
from thread_resolver.adapters.fake_editor import FakeEditingService
from thread_resolver.adapters.scripted_review import ScriptedReviewGate, approve_drafted_edits
from thread_resolver.adapters.sqlite_store import SqliteRunStore
from thread_resolver.app.pipeline import Limits, Resolver
from thread_resolver.config import MissingCredential, Settings
from thread_resolver.domain.run import RunState
from thread_resolver.ports.editor import EditingService
from thread_resolver.ports.judge import Judge

app = typer.Typer(
    add_completion=False,
    help="Walk the open comment threads in a .docx, draft the edit each one implies, "
    "and close the threads whose edit you approve.",
)
console = Console()


@app.command()
def run(
    document: Annotated[Path, typer.Argument(help="A .docx containing comment threads.")],
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Where to write the result.")
    ] = None,
    run_id: Annotated[str | None, typer.Option(help="Resume a previous run by its id.")] = None,
    max_threads: Annotated[
        int | None, typer.Option(help="Stop after this many open threads.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Classify and report only. No edits, no writes.")
    ] = False,
    offline: Annotated[
        bool, typer.Option("--offline", help="Use the built-in fake editor instead of the API.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", help="Approve every drafted edit without prompting.")
    ] = False,
    concurrency: Annotated[int, typer.Option(help="Edits requested at once.")] = 4,
    no_judge: Annotated[
        bool,
        typer.Option("--no-judge", help="Skip language judgement even if one is configured."),
    ] = False,
    database: Annotated[Path, typer.Option(help="Where run state is kept.")] = Path("runs.db"),
) -> None:
    """Resolve the comment threads in a document."""
    if not document.exists():
        console.print(f"[red]No such file:[/red] {document}")
        raise typer.Exit(code=2)
    if document.suffix.lower() != ".docx":
        console.print(
            f"[red]{document.suffix or 'This file'} is not supported.[/red] "
            "Comment threads with replies and resolved state exist only in .docx. "
            "Export or save your document as .docx and try again."
        )
        raise typer.Exit(code=2)

    source = DocxThreadSource.from_path(document)
    store = SqliteRunStore(database)
    identifier = run_id or f"run-{uuid.uuid4().hex[:8]}"

    editor = _editor(offline=offline, dry_run=dry_run)
    judge = _judge(no_judge=no_judge)
    gate = ScriptedReviewGate(rule=approve_drafted_edits) if yes else CliReviewGate(console)

    resolver = Resolver(
        source=source,
        editor=editor,
        store=store,
        gate=gate,
        judge=judge,
        limits=Limits(max_threads=max_threads, concurrency=concurrency, dry_run=dry_run),
    )

    judged = "gemini" if judge is not None else "no judge"
    console.print(f"[dim]run {identifier}  ·  {document.name}  ·  {judged}[/dim]")

    try:
        state = asyncio.run(resolver.run(identifier))
    except ReviewAborted as error:
        console.print(f"\n[yellow]{error}[/yellow]")
        console.print(
            f"[dim]Resume with: thread-resolver run {document} --run-id {identifier}[/dim]"
        )
        raise typer.Exit(code=1) from error
    except (UnsupportedDocument, WriteBackError, MissingCredential) as error:
        console.print(f"\n[red]{error}[/red]")
        raise typer.Exit(code=1) from error

    _report(state)

    if not dry_run and resolver.output is not None:
        destination = output or document.with_name(f"{document.stem}.resolved.docx")
        destination.write_bytes(resolver.output.data)
        console.print(f"\n[green]Wrote[/green] {destination}")

    console.print(f"[dim]run id {identifier}[/dim]")


@app.command()
def sample(
    destination: Annotated[Path, typer.Argument()] = Path("sample.docx"),
) -> None:
    """Write a document containing every kind of comment thread, to try this on."""
    from thread_resolver.samples import catalogue
    from thread_resolver.samples.builder import write_docx

    write_docx(catalogue.MIXED_DOCUMENT, destination)
    threads = DocxThreadSource.from_path(destination).read_threads()
    console.print(
        f"[green]Wrote[/green] {destination}  "
        f"({len(threads)} threads, {sum(1 for t in threads if t.is_open)} open)"
    )


@app.command(name="runs")
def list_runs(
    database: Annotated[Path, typer.Option(help="Where run state is kept.")] = Path("runs.db"),
) -> None:
    """List stored runs."""
    stored = SqliteRunStore(database).list_runs()
    if not stored:
        console.print("[dim]No runs recorded.[/dim]")
        return

    table = Table(box=None)
    table.add_column("run id")
    table.add_column("document")
    table.add_column("stage")
    table.add_column("threads", justify="right")
    table.add_column("decided", justify="right")
    for state in stored:
        table.add_row(
            state.run_id,
            state.document_name,
            str(state.stage),
            str(len(state.items)),
            str(sum(1 for item in state.items if item.is_decided)),
        )
    console.print(table)


def _editor(*, offline: bool, dry_run: bool) -> EditingService:
    if offline or dry_run:
        return FakeEditingService()

    settings = Settings()
    settings.require_superdocs_key()

    from thread_resolver.adapters.superdocs import SuperDocsEditingService

    return SuperDocsEditingService(settings)


def _judge(*, no_judge: bool) -> Judge | None:
    """The judge, if one is configured. Without it, multi-voice threads go to a person."""
    if no_judge:
        return None

    settings = Settings()
    if not settings.has_judge:
        return None

    from thread_resolver.adapters.gemini_judge import GeminiJudge

    return GeminiJudge(settings)


def _report(state: RunState) -> None:
    table = Table(title="Result", title_justify="left", box=None)
    table.add_column("disposition")
    table.add_column("threads", justify="right")

    for name, count in sorted(state.counts().items()):
        table.add_row(name, str(count))

    console.print()
    console.print(table)

    # Only an approved edit closes a thread; every other tally is still open.
    parts = [f"[bold]{len(state.closable)}[/bold] closed"]
    for count, label in (
        (len(state.approved), "approved"),
        (len(state.dismissed), "dismissed"),
        (len(state.deferred), "deferred"),
        (len(state.undecided), "undecided"),
    ):
        if count:
            parts.append(f"[bold]{count}[/bold] {label}")
    console.print("\n" + "  ·  ".join(parts))

    if state.timings:
        timings = "  ".join(f"{t.stage}={t.seconds}s" for t in state.timings)
        console.print(f"[dim]{timings}  total={round(state.total_seconds, 3)}s[/dim]")

    console.print(f"[dim]operations spent: {state.operations_spent}[/dim]")


if __name__ == "__main__":
    app()
