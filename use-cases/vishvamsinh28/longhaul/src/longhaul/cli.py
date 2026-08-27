"""The command line.

Every command is safe to run twice. ``run`` and ``resume`` are the same operation: a
run is resumable by construction, so there is no separate resume path to get wrong.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import report as report_mod
from .budget import OperationBudget
from .client import SuperDocsClient, SuperDocsError
from .config import load_settings
from .gate import build_gate, record_decisions
from .ledger import Ledger, LeaseLost
from .model import ADJUDICATE, FAILED, PLANNED, TERMINAL_STATES
from .planner import SpecError, load_spec, plan_run
from .runner import Runner

app = typer.Typer(
    add_completion=False,
    help="Run long document editing jobs that survive being killed.",
    no_args_is_help=True,
)
console = Console()

SpecOpt = typer.Option(..., "--spec", "-s", help="Path to a job spec YAML.")
RunOpt = typer.Option(None, "--run", "-r", help="Run id. Defaults to the newest run.")
StateOpt = typer.Option(None, "--state-dir", help="Where the ledger lives.")


def _ledger(state_dir: str | None) -> Ledger:
    return Ledger(load_settings(state_dir=state_dir).ledger_path)


def _client(state_dir: str | None = None) -> SuperDocsClient:
    settings = load_settings(state_dir=state_dir)
    if not settings.api_key:
        console.print(
            "[bold red]No API key.[/bold red] Set SUPERDOCS_API_KEY in your environment "
            "or .env file.\n[dim]Get one from use.superdocs.app -> Settings -> API Keys. "
            "Copy .env.example to .env to start.[/dim]"
        )
        raise typer.Exit(2)
    return SuperDocsClient(settings.api_key, settings.base_url)


def _resolve_run(ledger: Ledger, run_id: str | None) -> str:
    if run_id:
        return run_id
    runs = ledger.list_runs()
    if not runs:
        console.print("[red]No runs yet.[/red] Plan one: longhaul plan --spec <file>")
        raise typer.Exit(2)
    return runs[0].run_id


@app.command()
def plan(
    spec: str = SpecOpt,
    state_dir: Optional[str] = StateOpt,
    run_id: Optional[str] = typer.Option(
        None, "--run-id", help="Pin the run id instead of deriving one."
    ),
) -> None:
    """Compile a job spec into a durable plan. Makes no network calls."""
    try:
        job = load_spec(spec)
        with _ledger(state_dir) as ledger:
            run = plan_run(ledger, job, run_id=run_id)
    except SpecError as exc:
        console.print(f"[bold red]Bad spec:[/bold red] {exc}")
        raise typer.Exit(2) from exc
    console.print(
        f"[green]Planned[/green] [bold]{run.run_id}[/bold] — "
        f"{run.meta['step_count']} steps over {run.meta['document_count']} documents"
    )
    console.print(f"[dim]session {run.session_id}[/dim]")
    console.print(f"\nRun it:  longhaul run --run {run.run_id} --spec {spec}")


@app.command()
def run(
    spec: str = SpecOpt,
    run_id: Optional[str] = RunOpt,
    state_dir: Optional[str] = StateOpt,
    gate: Optional[str] = typer.Option(
        None, "--gate", "-g", help="policy | manual | deferred. Defaults to the spec."
    ),
    plan_if_missing: bool = typer.Option(
        True, "--plan/--no-plan", help="Plan a fresh run when none is given."
    ),
    json_out: Optional[str] = typer.Option(None, "--json", help="Write the report as JSON."),
    pin_run_id: Optional[str] = typer.Option(
        None, "--run-id", help="Pin the run id when planning a fresh run."
    ),
    max_operations: Optional[int] = typer.Option(
        None, "--max-operations", "-n",
        help="Stop after this many billable operations. The run resumes later, "
             "repeating nothing.",
    ),
    reserve: int = typer.Option(
        0, "--reserve",
        help="Leave this many operations unspent on the account. The run stops rather "
             "than dipping into them.",
    ),
) -> None:
    """Run a job, or continue one that was interrupted. The same command does both."""
    job = load_spec(spec)
    with _ledger(state_dir) as ledger:
        # --run-id names one exact run: resume it if it exists, plan it if it does not.
        # Without one, continue this spec's newest unfinished run, or start a fresh one.
        if run_id is None and pin_run_id and ledger.get_run(pin_run_id):
            run_id = pin_run_id
            console.print(f"[cyan]Resuming[/cyan] {run_id}")
        if run_id is None:
            existing = [r for r in ledger.list_runs() if r.spec_hash == job.spec_hash]
            unfinished = [r for r in existing if r.status != "completed"]
            if unfinished:
                run_id = unfinished[0].run_id
                console.print(f"[cyan]Resuming[/cyan] {run_id}")
            elif plan_if_missing:
                run_id = plan_run(ledger, job, run_id=pin_run_id).run_id
                console.print(f"[green]Planned[/green] {run_id}")
            else:
                console.print("[red]No run to continue.[/red]")
                raise typer.Exit(2)

        with _client(state_dir) as client:
            runner = Runner(
                ledger, client, job, build_gate(gate or job.gate.mode, job.gate),
                budget=OperationBudget(limit=max_operations, reserve=reserve),
            )
            try:
                outcome = runner.run(run_id)
            except LeaseLost as exc:
                console.print(f"[yellow]Another runner holds this run:[/yellow] {exc}")
                raise typer.Exit(3) from exc
            except SuperDocsError as exc:
                console.print(f"[bold red]{exc}[/bold red]")
                raise typer.Exit(1) from exc

        data = report_mod.build(ledger, outcome)

    report_mod.render(data, console)
    if json_out:
        Path(json_out).write_text(report_mod.to_json(data), encoding="utf-8")
    if report_mod.failed(data):
        raise typer.Exit(1)
    if not report_mod.succeeded(data):
        raise typer.Exit(4)  # blocked: a human has something to decide


@app.command()
def status(
    run_id: Optional[str] = RunOpt,
    state_dir: Optional[str] = StateOpt,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """What state is this run in, step by step, straight from the ledger."""
    with _ledger(state_dir) as ledger:
        rid = _resolve_run(ledger, run_id)
        meta = ledger.get_run(rid)
        steps = ledger.get_steps(rid)
        if json_out:
            print(json.dumps({
                "run_id": rid,
                "status": meta.status if meta else "unknown",
                "steps": [{"index": s.step_index, "id": s.step_id, "doc": s.doc_slug,
                           "state": s.state, "attempt": s.attempt,
                           "evidence": s.evidence} for s in steps],
            }, indent=2))
            return

        console.print(f"[bold]{rid}[/bold] — {meta.status if meta else 'unknown'}")
        table = Table(box=None, header_style="bold")
        for col in ("#", "step", "document", "state", "attempt", "job"):
            table.add_column(col)
        for s in steps:
            table.add_row(str(s.step_index), s.step_id, s.doc_slug, s.state,
                          str(s.attempt), s.job_id or "-")
        console.print(table)
        remaining = [s for s in steps if s.state not in TERMINAL_STATES]
        if remaining:
            console.print(
                f"\n[cyan]Resume point:[/cyan] step {remaining[0].step_index} "
                f"({remaining[0].state}) — recovered from the ledger, not from memory."
            )


@app.command()
def pending(
    run_id: Optional[str] = RunOpt,
    state_dir: Optional[str] = StateOpt,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Proposed changes waiting on a decision."""
    with _ledger(state_dir) as ledger:
        rid = _resolve_run(ledger, run_id)
        out = []
        for step in ledger.get_steps(rid):
            proposals = ledger.get_proposals(rid, step.step_index)
            decided = {d.change_id for d in ledger.get_decisions(rid, step.step_index)}
            waiting = [p for p in proposals if p.change_id not in decided]
            if waiting:
                out.append({
                    "step_index": step.step_index, "step_id": step.step_id,
                    "document": step.doc_slug,
                    "changes": [p.to_public() for p in waiting],
                })
    if json_out:
        print(json.dumps(out, indent=2))
        return
    if not out:
        console.print("[green]Nothing is waiting on a decision.[/green]")
        return
    for entry in out:
        console.print(f"\n[bold]step {entry['step_index']}[/bold] "
                      f"{entry['step_id']} · {entry['document']}")
        for c in entry["changes"]:
            console.print(f"  [cyan]{c['change_id']}[/cyan] {c['operation']}: "
                          f"{c['ai_explanation']}")


@app.command()
def decide(
    step: int = typer.Option(..., "--step", help="Step index the changes belong to."),
    approve: list[str] = typer.Option([], "--approve", "-a", help="change_id to approve."),
    reject: list[str] = typer.Option([], "--reject", "-x", help="change_id to reject."),
    feedback: Optional[str] = typer.Option(None, "--feedback", help="Reason for rejections."),
    run_id: Optional[str] = RunOpt,
    state_dir: Optional[str] = StateOpt,
) -> None:
    """Record decisions on proposed changes, item by item.

    Approving some and rejecting others in one call is the normal case; a rejection never
    discards the rest. The run picks these up on its next resume.
    """
    if not approve and not reject:
        console.print("[red]Nothing to decide.[/red] Pass --approve and/or --reject.")
        raise typer.Exit(2)
    verdicts = {cid: (True, None) for cid in approve}
    verdicts.update({cid: (False, feedback) for cid in reject})
    with _ledger(state_dir) as ledger:
        rid = _resolve_run(ledger, run_id)
        try:
            decisions = record_decisions(ledger, rid, step, verdicts, decided_by="cli")
        except ValueError as exc:
            console.print(f"[bold red]{exc}[/bold red]")
            raise typer.Exit(2) from exc
    console.print(
        f"[green]Recorded[/green] {sum(1 for d in decisions if d.approved)} approved, "
        f"{sum(1 for d in decisions if not d.approved)} rejected on step {step}."
    )


@app.command()
def export(
    run_id: Optional[str] = RunOpt,
    state_dir: Optional[str] = StateOpt,
    out_dir: str = typer.Option("out", "--out", "-o"),
    fmt: str = typer.Option("markdown", "--format", "-f",
                            help="docx | pdf | html | markdown | txt"),
) -> None:
    """Export every document in the run. Exports never cost operations."""
    with _ledger(state_dir) as ledger:
        rid = _resolve_run(ledger, run_id)
        meta = ledger.get_run(rid)
        if meta is None:
            console.print(f"[red]No run {rid}[/red]")
            raise typer.Exit(2)
        documents = ledger.get_documents(rid)
        target = Path(out_dir) / rid
        target.mkdir(parents=True, exist_ok=True)
        suffix = {"markdown": "md", "docx": "docx", "pdf": "pdf",
                  "html": "html", "txt": "txt"}.get(fmt, fmt)
        with _client(state_dir) as client:
            for doc in documents:
                if not doc.document_id:
                    console.print(f"[yellow]skip {doc.slug}: never opened[/yellow]")
                    continue
                blob = client.export_document(
                    meta.session_id, doc.document_id, fmt=fmt
                )
                path = target / f"{doc.slug}.{suffix}"
                path.write_bytes(blob)
                console.print(f"[green]{path}[/green] ({len(blob)} bytes)")


@app.command()
def adjudicate(
    step: int = typer.Option(..., "--step"),
    resolve: str = typer.Option(
        ..., "--resolve",
        help="done = the work landed, close it. replan = it did not, run it again.",
    ),
    run_id: Optional[str] = RunOpt,
    state_dir: Optional[str] = StateOpt,
) -> None:
    """Settle a step the runner refused to guess about.

    Reaching here means the evidence was genuinely inconclusive. The system stopped
    rather than risk applying an edit twice or skipping one; this is where a person who
    has looked at the document says which it was.
    """
    if resolve not in ("done", "replan"):
        console.print("[red]--resolve must be 'done' or 'replan'[/red]")
        raise typer.Exit(2)
    with _ledger(state_dir) as ledger:
        rid = _resolve_run(ledger, run_id)
        current = ledger.get_step(rid, step)
        if current.state not in (ADJUDICATE, FAILED):
            console.print(
                f"[yellow]Step {step} is {current.state!r}, not awaiting adjudication.[/yellow]"
            )
            raise typer.Exit(2)
        target = "done" if resolve == "done" else PLANNED
        ledger.transition(
            rid, step, expect=(ADJUDICATE, FAILED), to=target,
            evidence=f"adjudicated by a human: {resolve}",
            disposition="adjudicated: " + resolve,
        )
    console.print(f"[green]Step {step} adjudicated as {resolve}.[/green]")


@app.command()
def doctor(state_dir: Optional[str] = StateOpt) -> None:
    """Check the key and the connection before spending anything."""
    settings = load_settings(state_dir=state_dir)
    console.print(f"base url  : {settings.base_url}")
    console.print(f"api key   : {settings.redacted()}")
    console.print(f"ledger    : {settings.ledger_path}")
    if not settings.api_key:
        console.print("[red]No API key set.[/red] Copy .env.example to .env and fill it in.")
        raise typer.Exit(2)
    try:
        with SuperDocsClient(settings.api_key, settings.base_url) as client:
            client.ping()
    except SuperDocsError as exc:
        console.print(f"[bold red]Cannot reach SuperDocs:[/bold red] {exc}")
        raise typer.Exit(1) from exc
    console.print("[green]Key works.[/green] (GET /v1/sessions costs no operations.)")


@app.command()
def runs(state_dir: Optional[str] = StateOpt) -> None:
    """List runs, newest first."""
    with _ledger(state_dir) as ledger:
        table = Table(box=None, header_style="bold")
        for col in ("run", "job", "status", "steps", "session"):
            table.add_column(col)
        for r in ledger.list_runs():
            done = sum(1 for s in ledger.get_steps(r.run_id) if s.is_terminal)
            total = len(ledger.get_steps(r.run_id))
            table.add_row(r.run_id, str(r.meta.get("job_name", "-")), r.status,
                          f"{done}/{total}", r.session_id)
        console.print(table)


@app.command()
def serve(
    spec: str = SpecOpt,
    run_id: Optional[str] = RunOpt,
    state_dir: Optional[str] = StateOpt,
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8420, "--port"),
) -> None:
    """Open the review UI: approve and reject changes in a browser."""
    import uvicorn

    from .web import create_app

    console.print(f"[green]Review UI[/green] http://{host}:{port}")
    uvicorn.run(
        create_app(spec, run_id, state_dir), host=host, port=port, log_level="warning"
    )


def main() -> None:  # pragma: no cover
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped. Nothing was lost; resume with the same command.[/yellow]")
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
