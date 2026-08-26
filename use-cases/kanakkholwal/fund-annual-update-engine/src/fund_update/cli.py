"""The `fund-update` command.

`plan` runs offline and shows exactly what would change. `run` drives SuperDocs end to end and
stops at the reviewer, because nothing here is allowed to commit itself.
"""

import sys
import time

import typer
from rich.console import Console
from rich.table import Table

from fund_update.config import load_settings
from fund_update.domain import guards as guard_checks
from fund_update.domain.documents import read_document, read_set
from fund_update.domain.fieldmap import load_fieldmap
from fund_update.domain.plan import Plan, build_plan, read_figures, write_reference_markdown
from fund_update.domain.reporting import write_changelog_docx, write_review_html
from fund_update.superdocs.client import (
    OperationBudgetExceeded,
    SuperDocsClient,
    SuperDocsError,
    save_export,
)

cli = typer.Typer(
    name="fund-update",
    help="Annual refresh of a fund document set on SuperDocs.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _export_when_applied(
    client: SuperDocsClient,
    session_id: str,
    document: str,
    expected: set[str],
    final_dir,
    fmt: str,
    attempts: int = 12,
    pause: float = 15.0,
):
    """Approved changes apply asynchronously, so an export taken too early is the old document.

    Exports are free, so this re-exports until the requested values are actually present.
    """
    saved = None
    for attempt in range(1, attempts + 1):
        body = client.export(session_id, fmt, filename=f"{document}.{fmt}")
        saved = save_export(body, final_dir / f"{document}.{fmt}")
        if saved and guard_checks.check_intended_values_landed(
            read_document(document, saved), expected
        ).ok:
            return saved, attempt
        if attempt < attempts:
            time.sleep(pause)
    return saved, attempts


def _build_plan(settings, sample: int) -> tuple[Plan, dict]:
    fieldmap = load_fieldmap()
    views = read_set(settings.baseline_dir, fieldmap)
    figures = read_figures(settings.data_file)
    return build_plan(views, figures, fieldmap, sample=sample or settings.sample), fieldmap


def _show(plan: Plan) -> None:
    table = Table(title="Proposed changes", show_lines=False, header_style="bold")
    for column in ("Document", "Field", "Was", "Becomes", "Source"):
        table.add_column(column, overflow="fold")
    for edit in plan.edits:
        table.add_row(edit.document, edit.label, edit.old_value, edit.new_value, edit.citation)
    console.print(table)

    if plan.unchanged:
        console.print(f"[dim]Unchanged, so not edited and not paid for:[/dim] {', '.join(plan.unchanged)}")
    for item in plan.unresolved:
        console.print(f"[yellow]needs a human:[/yellow] {item.label} — {item.reason}")
    console.print(f"\n[bold]{plan.summary()}[/bold]")


@cli.command()
def plan(sample: int = typer.Option(0, help="only consider the first N fields (cheap dry run)")) -> None:
    """Show what would change. No API key, no network, no spend."""
    settings = load_settings()
    result, _ = _build_plan(settings, sample)
    _show(result)

    review = write_review_html(result, {}, settings.out_dir / "review" / "marked-version.html")
    changelog = write_changelog_docx(result, settings.out_dir / "review" / "change-log.docx")
    console.print(f"\nmarked version : {review}")
    console.print(f"change log     : {changelog}")
    console.print(
        f"\n[dim]{result.operations} operation(s) would be spent: edits are batched one request "
        f"per document, and one request covers up to 25 targeted sections.[/dim]"
    )


@cli.command()
def whoami() -> None:
    """Check the account tier and how many operations are left."""
    settings = load_settings()
    with SuperDocsClient(settings.api_key, settings.api_base) as client:
        console.print(client.whoami())


@cli.command()
def run(
    approve_all: bool = typer.Option(False, help="approve every proposed change without prompting"),
    sample: int = typer.Option(0, help="only process the first N fields"),
    fmt: str = typer.Option("docx", help="export format for the clean final"),
) -> None:
    """Upload, edit, review, approve, export. Stops at the reviewer unless --approve-all."""
    settings = load_settings()
    if not settings.has_key:
        console.print(
            "[red]No SUPERDOCS_API_KEY.[/red] Copy .env.example to .env and add a key from "
            "use.superdocs.app. `fund-update plan` works without one."
        )
        raise typer.Exit(2)

    result, fieldmap = _build_plan(settings, sample)
    _show(result)
    if not result.edits:
        console.print("[green]Nothing changed. No operations spent.[/green]")
        raise typer.Exit(0)

    final_dir = settings.out_dir / "final"
    decisions_taken: dict[str, str] = {}

    with SuperDocsClient(
        settings.api_key, settings.api_base, max_operations=settings.max_operations
    ) as client:
        try:
            reference = write_reference_markdown(
                read_figures(settings.data_file), settings.out_dir / "reference" / "approved-figures.md"
            )

            for document, edits in sorted(result.by_document().items()):
                # One session per document: an upload replaces a session's document rather
                # than adding one, so three documents need three sessions.
                session_id = client.start_session()
                console.print(f"\n[bold]{document}[/bold]  session {session_id}")

                spec = fieldmap.documents[document]
                client.upload_document(settings.baseline_dir / spec.filename, session_id)
                client.upload_reference(reference, session_id)
                console.print(f"  uploaded {spec.filename}, attached {reference.name}")

                instructions = "\n".join(f"{i}. {e.instruction()}" for i, e in enumerate(edits, 1))
                message = (
                    f"Apply exactly these {len(edits)} value updates to this document. "
                    f"Make no other change of any kind. The figures come from the attached data "
                    f"file; do not use any other source and do not compute anything.\n\n{instructions}"
                )
                console.print(f"  requesting {len(edits)} targeted edits")
                job = client.request_edit(session_id, message)
                console.print(f"  job {job.job_id} ([dim]this can take minutes; that is not a crash[/dim])")

                state = client.await_job(job.job_id)
                console.print(f"  status {state.status}, {len(state.changes)} proposed change(s)")
                if state.finished and not state.changes:
                    console.print(
                        f"  [yellow]no changes proposed: {str(state.result.get('response', ''))[:160]}[/yellow]"
                    )

                decisions = []
                for change in state.changes:
                    approved = approve_all or typer.confirm(f"    approve: {change.summary[:120]}?")
                    decisions.append((change.change_id, approved, "" if approved else "rejected by reviewer"))
                    decisions_taken[f"{document}:{change.change_id}"] = "approved" if approved else "rejected"
                if decisions:
                    client.decide(session_id, job.job_id, decisions)
                    console.print(f"  committed {sum(1 for _, a, _ in decisions if a)} approval(s)")

                expected_values = {e.new_value for e in edits}
                saved, attempts = _export_when_applied(
                    client, session_id, document, expected_values, final_dir, fmt
                )
                if saved:
                    console.print(f"  exported {saved.name} (verified after {attempts} export(s))")
                pdf = save_export(
                    client.export(session_id, "pdf", filename=f"{document}.pdf"),
                    final_dir / f"{document}.pdf",
                )
                if pdf:
                    console.print(f"  exported {pdf.name}")

        except OperationBudgetExceeded as exc:
            console.print(f"[yellow]{exc}[/yellow]")
        except SuperDocsError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc

        console.print(
            f"\n[dim]{client.usage.operations} operation(s), {client.usage.requests} request(s), "
            f"{client.usage.seconds:.1f}s of API time.[/dim]"
        )

    expected = {doc: {e.new_value for e in edits} for doc, edits in result.by_document().items()}
    checks = guard_checks.run_all(settings.baseline_dir, final_dir, fieldmap, expected, pdf_dir=final_dir)
    for document, outcome in sorted(checks.items()):
        colour = "green" if outcome.ok else "red"
        console.print(f"[{colour}]{document}: {'passed' if outcome.ok else 'FAILED'}[/{colour}]")
        for line in outcome.failures:
            console.print(f"   [red]{line}[/red]")
        for line in outcome.warnings:
            console.print(f"   [yellow]{line}[/yellow]")

    review = write_review_html(result, checks, settings.out_dir / "review" / "marked-version.html")
    changelog = write_changelog_docx(result, settings.out_dir / "review" / "change-log.docx", decisions_taken)
    console.print(f"\nmarked version : {review}")
    console.print(f"change log     : {changelog}")
    console.print(f"clean finals   : {final_dir}")

    if any(not c.ok for c in checks.values()):
        console.print("\n[red]Guards failed. The export is not releasable.[/red]")
        raise typer.Exit(1)


def main() -> None:
    sys.exit(cli())


if __name__ == "__main__":
    main()
