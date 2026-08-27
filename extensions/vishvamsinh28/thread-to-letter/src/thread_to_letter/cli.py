"""The command line.

One run is two billable operations: one to extract the commitments, one to write the
letter. Everything else — parsing, quote checking, export, building the reply — is free.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import draft as draft_mod
from . import extract as extract_mod
from . import letter as letter_mod
from .client import Client, SuperDocsError
from .commitments import Commitment, dangling_superseded, summarise
from .config import load_settings
from .injection import scan_thread
from .thread import Thread, load

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Turn a messy email thread into a letter that states only what was committed to.",
)
console = Console()

_STATUS_STYLE = {
    "firm": "green", "superseded": "yellow", "hedged": "cyan",
    "second-hand": "magenta", "proposed": "blue",
}


def _client() -> Client:
    settings = load_settings()
    if not settings.api_key:
        console.print(
            "[bold red]No API key.[/bold red] Copy .env.example to .env and put your key "
            "in it.\n[dim]Get one from use.superdocs.app -> Settings -> API Keys.[/dim]"
        )
        raise typer.Exit(2)
    return Client(settings.api_key, settings.base_url)


def _session(thread: Thread) -> str:
    import hashlib

    digest = hashlib.sha256(thread.normalised.encode()).hexdigest()[:12]
    return f"thread2letter-{digest}"


def _show_thread(thread: Thread) -> None:
    table = Table(box=None, header_style="bold", pad_edge=False)
    for col in ("#", "from", "date", "opening"):
        table.add_column(col)
    for m in thread.messages:
        opening = " ".join(m.body.split())[:70]
        table.add_row(str(m.index), m.sender, (m.date or "")[:22], opening)
    console.print(table)


def _show_commitments(commitments: list[Commitment]) -> None:
    if not commitments:
        console.print("[dim]Nothing was extracted.[/dim]")
        return
    table = Table(box=None, header_style="bold", pad_edge=False)
    for col in ("#", "status", "party", "obligation", "due", "src", "quote"):
        table.add_column(col, overflow="fold")
    for i, c in enumerate(commitments, start=1):
        style = _STATUS_STYLE.get(c.status, "white")
        mark = "" if c.quote_found else " [bold red](unverified)[/bold red]"
        table.add_row(
            str(i), f"[{style}]{c.status}[/{style}]{mark}", c.party,
            c.obligation[:46], c.due or "—", c.source or "—",
            f'[dim]"{c.quote[:60]}"[/dim]',
        )
    console.print(table)
    for i, c in enumerate(commitments, start=1):
        if c.quote_note:
            colour = "red" if not c.quote_found else "yellow"
            console.print(f"  [{colour}]{i}: {c.quote_note}[/{colour}]")


def _gate(commitments: list[Commitment], auto: bool) -> list[Commitment]:
    """Which commitments go into the letter. A human decides unless told otherwise."""
    default = [c for c in commitments if c.usable]
    if auto:
        return default
    if not commitments:
        return []

    console.print(
        "\n[bold]Which of these go in the letter?[/bold]\n"
        "[dim]Enter to accept the firm, verified ones (marked green). "
        "Or type numbers, e.g. 1,3[/dim]"
    )
    console.print(
        f"[dim]default: {', '.join(str(i + 1) for i, c in enumerate(commitments) if c.usable) or 'none'}[/dim]"
    )
    console.print("> ", end="")
    try:
        answer = input().strip()
    except EOFError:
        answer = ""
    if not answer:
        return default

    chosen: list[Commitment] = []
    for token in answer.replace(" ", "").split(","):
        if not token.isdigit():
            continue
        idx = int(token) - 1
        if 0 <= idx < len(commitments):
            chosen.append(commitments[idx])
    return chosen


@app.command()
def show(thread_path: str = typer.Argument(..., help="A .mbox, .eml or pasted thread.")) -> None:
    """Parse a thread and show what was read. Makes no API calls and costs nothing."""
    thread = load(thread_path)
    console.print(Panel(f"[bold]{thread.subject}[/bold]\n"
                        f"[dim]{len(thread.messages)} messages · "
                        f"{', '.join(thread.participants)}[/dim]"))
    _show_thread(thread)
    findings = scan_thread(thread)
    if findings:
        console.print(Panel(
            "\n".join(f.render() for f in findings),
            title="[bold yellow]Text in this thread addressed to an automated reader[/bold yellow]",
            subtitle="reported as data; it is never followed",
        ))


@app.command()
def doctor() -> None:
    """Check the key and the connection. Costs nothing."""
    settings = load_settings()
    console.print(f"base url : {settings.base_url}"
                  f"{'  [green](live)[/green]' if settings.is_live else ''}")
    console.print(f"api key  : {settings.redacted()}")
    if not settings.api_key:
        console.print("[red]No API key set.[/red] Copy .env.example to .env.")
        raise typer.Exit(2)
    try:
        with _client() as client:
            client.ping()
    except SuperDocsError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc
    console.print("[green]Key works.[/green] (GET /v1/sessions costs no operations.)")


@app.command()
def run(
    thread_path: str = typer.Argument(..., help="A .mbox, .eml or pasted thread."),
    shape: str = typer.Option("letter", "--shape", help="letter | memo"),
    fmt: str = typer.Option("docx", "--format", "-f",
                            help="docx | pdf | html | markdown | txt"),
    out_dir: str = typer.Option("out", "--out", "-o"),
    auto: bool = typer.Option(False, "--auto",
                              help="Accept the firm, verified commitments without asking."),
    model_tier: Optional[str] = typer.Option(None, "--model-tier",
                                             help="core | pro | max | turbo"),
    from_address: str = typer.Option("", "--from", help="Your address, for the reply draft."),
) -> None:
    """Thread in, letter out, attached to a reply draft. Two billable operations."""
    thread = load(thread_path)
    console.print(Panel(f"[bold]{thread.subject}[/bold]\n"
                        f"[dim]{len(thread.messages)} messages · "
                        f"{', '.join(thread.participants)}[/dim]"))

    findings = scan_thread(thread)
    if findings:
        console.print(Panel(
            "\n".join(f.render() for f in findings),
            title="[bold yellow]Text addressed to an automated reader[/bold yellow]",
            subtitle="reported as data; the letter is built from confirmed commitments only",
        ))

    session = _session(thread)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)

    try:
        with _client() as client:
            console.print("\n[dim]Extracting commitments…[/dim]")
            extraction = extract_mod.extract(client, thread, session, model_tier=model_tier)

            if extraction.found_nothing:
                console.print("[bold green]No commitments were made in this thread.[/bold green]")
                console.print("[dim]That is a real answer, and the letter will say so.[/dim]")
            _show_commitments(extraction.commitments)

            counts = summarise(extraction.commitments)
            console.print(
                f"\n[bold]{counts['usable']}[/bold] firm and verified · "
                f"[bold]{counts.get('superseded', 0)}[/bold] superseded · "
                f"[bold]{counts.get('hedged', 0)}[/bold] hedged · "
                f"[bold]{counts.get('second-hand', 0)}[/bold] second-hand · "
                f"[bold]{counts['unverified']}[/bold] could not be quoted"
            )

            # If something was superseded then something replaced it, and the
            # replacement is the one that belongs in the letter. Writing a letter
            # without it looks complete while omitting the obligation the thread was
            # about, so this stops rather than producing one.
            dangling = dangling_superseded(extraction.commitments)
            if dangling:
                console.print(Panel(
                    "\n".join(
                        f"{c.party} was recorded as superseding an earlier commitment "
                        f"({c.obligation}, {c.due or 'no date'}), but the replacement "
                        f"is not in the list."
                        for c in dangling
                    ),
                    title="[bold red]A replaced commitment has no replacement[/bold red]",
                    subtitle="the letter would be missing the obligation that actually stands",
                ))
                if auto:
                    console.print(
                        "[bold red]Stopping.[/bold red] Re-run without --auto to choose "
                        "by hand, or check the thread — the extraction is incomplete."
                    )
                    raise typer.Exit(3)

            confirmed = _gate(extraction.commitments, auto)
            console.print(f"[dim]{len(confirmed)} commitment(s) will go in the letter.[/dim]")

            console.print("[dim]Drafting…[/dim]")
            today = _dt.date.today().strftime("%d %B %Y")
            result = letter_mod.draft(
                client, thread, confirmed, session, shape=shape,
                today=today, model_tier=model_tier,
            )

            blob = client.export(session_id=session, fmt=fmt,
                                 options={"filename": draft_mod._slug(thread.subject)})
            letter_path = draft_mod.write(target / f"{draft_mod._slug(thread.subject)}."
                                          f"{draft_mod._SUFFIX.get(fmt, fmt)}", blob)

            reply = draft_mod.build_reply(
                thread, confirmed, blob, fmt=fmt, from_address=from_address,
                stem=draft_mod._slug(thread.subject),
            )
            reply_path = draft_mod.write(target / f"reply-{draft_mod._slug(thread.subject)}.eml",
                                         reply)
            spent = client.operations_spent
    except SuperDocsError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc

    (target / "commitments.json").write_text(
        json.dumps([c.to_public() for c in extraction.commitments], indent=2),
        encoding="utf-8",
    )
    console.print(
        f"\n[green]{letter_path}[/green] ({len(blob)} bytes)\n"
        f"[green]{reply_path}[/green] — open it in your mail client to send\n"
        f"[dim]{target / 'commitments.json'} — the evidence, including what was rejected[/dim]"
    )
    console.print(f"[dim]{spent} operations spent.[/dim]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8430, "--port"),
    threads_dir: str = typer.Option("threads", "--threads"),
) -> None:
    """Open the console: pick a thread, review what was committed, write the letter."""
    import uvicorn

    from .web import create_app

    console.print(f"[green]Console[/green] http://{host}:{port}")
    console.print("[dim]It spends nothing until you press a button.[/dim]")
    uvicorn.run(create_app(threads_dir), host=host, port=port, log_level="warning")


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
