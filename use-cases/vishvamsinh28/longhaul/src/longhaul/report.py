"""The run report.

Two rules, both from CONTRACT.md I5:

* A step is described by what actually happened to it, including *why* the runner
  believes that. "Skipped" always carries the evidence that justified skipping.
* A success line is only ever printed for a run whose every step reached a terminal
  state. A run with an unresolved step reports ``blocked``, never ``completed``.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .ledger import Ledger
from .model import ADJUDICATE, RUN_COMPLETED, RUN_FAILED
from .runner import RunOutcome

_STATE_STYLE = {
    "done": "green",
    "rejected": "yellow",
    "adjudicate": "bold red",
    "failed": "bold red",
}


def build(ledger: Ledger, outcome: RunOutcome) -> dict[str, Any]:
    """The machine-readable report. The rendered one is a view of this, never a separate
    account, so what a person reads and what a program reads cannot disagree."""
    run = ledger.get_run(outcome.run_id)
    steps = ledger.get_steps(outcome.run_id)
    commits = ledger.get_commits(outcome.run_id)
    documents = ledger.get_documents(outcome.run_id)

    return {
        "run_id": outcome.run_id,
        "status": outcome.status,
        "job": (run.meta.get("job_name") if run else None),
        "session_id": run.session_id if run else None,
        "blocked_reason": outcome.blocked_reason,
        "paused_at": outcome.paused_at,
        "totals": {
            "steps": len(steps),
            "executed": outcome.executed,
            "skipped_already_done": outcome.skipped,
            "adjudicate": sum(1 for s in steps if s.state == ADJUDICATE),
            "changes_approved": sum(1 for c in commits if c.approved),
            "changes_rejected": sum(1 for c in commits if not c.approved),
            "billable_operations": sum(s.billable_ops for s in steps),
            "account_operations_remaining": outcome.account_remaining,
            "wall_ms": outcome.wall_ms,
            "step_ms": sum(s.duration_ms for s in steps),
        },
        # A mean would hide the step that took four minutes behind seven that took ten
        # seconds, and the slow one is the whole reason a job needs to be resumable.
        "step_latency_ms": _distribution([s.duration_ms for s in steps if s.duration_ms]),
        "documents": [
            {"slug": d.slug, "title": d.title, "document_id": d.document_id,
             "source_sha256": d.source_sha256}
            for d in documents
        ],
        "steps": [asdict(s) for s in outcome.steps],
        "findings": [
            {"kind": f.kind, "where": f.where, "excerpt": f.excerpt}
            for f in outcome.findings
        ],
        "commit_log": [
            {"step_index": c.step_index, "change_id": c.change_id,
             "approved": c.approved, "document_id": c.document_id}
            for c in commits
        ],
    }


def _distribution(values: list[int]) -> dict[str, Any]:
    """Spread, not a single number.

    Reported as median, p95, slowest and range rather than an average, because what
    matters operationally is the tail: the step that runs long is the one an interruption
    is most likely to land in.
    """
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    n = len(ordered)

    def pct(q: float) -> int:
        # Nearest-rank, so every reported figure is a measurement that actually occurred
        # rather than an interpolation between two that did not.
        return ordered[min(n - 1, max(0, math.ceil(q * n) - 1))]

    return {
        "count": n,
        "min_ms": ordered[0],
        "p50_ms": pct(0.50),
        "p95_ms": pct(0.95),
        "max_ms": ordered[-1],
        "spread_ms": ordered[-1] - ordered[0],
    }


def render(report: dict[str, Any], console: Console | None = None) -> None:
    console = console or Console()
    totals = report["totals"]

    status = report["status"]
    style = {"completed": "bold green", "blocked": "bold yellow"}.get(status, "bold red")
    headline = f"[{style}]{status.upper()}[/{style}]  run {report['run_id']}"
    if report.get("blocked_reason"):
        headline += f"\n[yellow]{report['blocked_reason']}[/yellow]"
    console.print(Panel(headline, title=report.get("job") or "longhaul"))

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for col in ("#", "step", "document", "state", "disposition", "ok", "no", "ms", "ops"):
        table.add_column(col, justify="right" if col in ("#", "ok", "no", "ms", "ops") else "left")
    for s in report["steps"]:
        table.add_row(
            str(s["step_index"]), s["step_id"], s["doc_slug"],
            f"[{_STATE_STYLE.get(s['state'], 'white')}]{s['state']}[/]",
            _disposition_style(s["disposition"]),
            str(s["approved"]), str(s["rejected"]),
            str(s["duration_ms"]), str(s["billable_ops"]),
        )
    console.print(table)

    # Evidence for anything not executed this attempt. Without this the word "skipped"
    # would be an assertion rather than a claim anyone could check.
    for s in report["steps"]:
        if s["disposition"] != "executed" and s.get("evidence"):
            console.print(f"  [dim]step {s['step_index']}: {s['evidence']}[/dim]")

    console.print(
        f"\n[bold]{totals['executed']}[/bold] executed · "
        f"[bold]{totals['skipped_already_done']}[/bold] skipped as already-done · "
        f"[bold]{totals['adjudicate']}[/bold] awaiting adjudication"
    )
    console.print(
        f"[bold]{totals['changes_approved']}[/bold] changes approved · "
        f"[bold]{totals['changes_rejected']}[/bold] rejected · "
        f"[bold]{totals['billable_operations']}[/bold] billable operations · "
        f"[bold]{totals['wall_ms']}[/bold] ms wall"
    )

    spread = report.get("step_latency_ms") or {}
    if spread.get("count"):
        remaining = totals.get("account_operations_remaining")
        console.print(
            f"[dim]step latency over {spread['count']} steps — "
            f"median {spread['p50_ms']} ms · p95 {spread['p95_ms']} ms · "
            f"slowest {spread['max_ms']} ms · fastest {spread['min_ms']} ms[/dim]"
        )
        if isinstance(remaining, int):
            console.print(
                f"[dim]{remaining} operations left on the account[/dim]"
            )

    if report["findings"]:
        console.print(Panel(
            "\n".join(f"[yellow]{f['kind']}[/yellow] in [bold]{f['where']}[/bold]: {f['excerpt']}"
                      for f in report["findings"]),
            title="[bold yellow]Documents that tried to give orders[/bold yellow]",
            subtitle="reported as data; none of it was executed",
        ))
    else:
        # The rarest output in this industry, and worth printing plainly.
        console.print("[dim]No document in this set attempted to issue instructions.[/dim]")


def _disposition_style(disposition: str) -> str:
    if disposition == "executed":
        return "[green]executed[/green]"
    if disposition.startswith("skipped"):
        return f"[cyan]{disposition}[/cyan]"
    if disposition == "adjudicate":
        return "[bold red]adjudicate[/bold red]"
    return f"[yellow]{disposition}[/yellow]"


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True)


def succeeded(report: dict[str, Any]) -> bool:
    return report["status"] == RUN_COMPLETED


def failed(report: dict[str, Any]) -> bool:
    return report["status"] == RUN_FAILED
