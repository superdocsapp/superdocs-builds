"""Longhaul as an MCP server.

The point of this surface is behaviour four from the brief: another program can drive the
whole flow end to end without a human clicking through an interface — **and the approval
gate is part of that flow**, not a detour around it. ``list_pending_changes`` and
``decide_changes`` are ordinary tools, so whoever drives the run, human or program, makes
the approval call explicitly and on the record.

Decisions arrive through :func:`longhaul.gate.record_decisions`, the same function the
CLI and the web UI use. Three surfaces, one decision path, no drift.

Run it::

    uv run longhaul-mcp --spec jobs/runbook-migration.yaml
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .client import SuperDocsClient, SuperDocsError
from .config import load_settings
from .budget import OperationBudget
from .gate import DeferredGate, PolicyGate, record_decisions
from .ledger import Ledger, LeaseLost
from .model import ADJUDICATE, FAILED, PLANNED, TERMINAL_STATES
from .planner import load_spec, plan_run
from .report import build
from .runner import Runner

server = MCPServer(
    name="longhaul",
    instructions=(
        "Runs long, multi-step SuperDocs editing jobs that survive being killed. Plan a "
        "job, advance it, review the changes it proposes, decide them one by one, and "
        "export the result. Calling advance_run again after any interruption continues "
        "from the last committed step; it never replays work that is already done."
    ),
)

_SPEC_ENV = "LONGHAUL_SPEC"


def _spec_path(override: str | None = None) -> str:
    path = override or os.environ.get(_SPEC_ENV)
    if not path:
        raise ValueError(
            "no job spec: pass spec_path, or start the server with --spec"
        )
    return path


def _ledger() -> Ledger:
    return Ledger(load_settings().ledger_path)


def _resolve(ledger: Ledger, run_id: str | None) -> str:
    if run_id:
        return run_id
    runs = ledger.list_runs()
    if not runs:
        raise ValueError("no runs exist yet; call plan_run first")
    return runs[0].run_id


@server.tool(
    description="Compile a job spec into a durable plan. Makes no network calls and "
                "spends nothing. Returns the run id everything else refers to."
)
def plan_job(
    spec_path: Annotated[str | None, Field(description="Path to a job YAML.")] = None,
) -> dict[str, Any]:
    spec = load_spec(_spec_path(spec_path))
    with _ledger() as ledger:
        run = plan_run(ledger, spec)
        return {
            "run_id": run.run_id,
            "session_id": run.session_id,
            "job": spec.name,
            "steps": run.meta["step_count"],
            "documents": run.meta["document_count"],
        }


@server.tool(
    description="Run a job forward until it finishes or needs a decision. Safe to call "
                "again after any interruption: steps already done are reported as "
                "skipped, never re-issued. With gate='deferred' the run pauses for "
                "review; with gate='policy' it applies the spec's own rules."
)
def advance_run(
    run_id: Annotated[str | None, Field(description="Defaults to the newest run.")] = None,
    gate: Annotated[str, Field(description="'deferred' or 'policy'.")] = "deferred",
    spec_path: Annotated[str | None, Field(description="Path to a job YAML.")] = None,
    max_operations: Annotated[
        int | None,
        Field(description="Stop after this many billable operations; the run resumes "
                          "later and repeats nothing."),
    ] = None,
    reserve: Annotated[
        int, Field(description="Leave this many operations unspent on the account.")
    ] = 0,
) -> dict[str, Any]:
    spec = load_spec(_spec_path(spec_path))
    settings = load_settings()
    if not settings.api_key:
        return {"error": "SUPERDOCS_API_KEY is not set", "status": "not_started"}

    with _ledger() as ledger:
        rid = _resolve(ledger, run_id) if run_id or ledger.list_runs() else \
            plan_run(ledger, spec).run_id
        chosen = DeferredGate() if gate == "deferred" else PolicyGate(spec.gate)
        try:
            with SuperDocsClient(settings.api_key, settings.base_url) as client:
                outcome = Runner(
                    ledger, client, spec, chosen,
                    budget=OperationBudget(limit=max_operations, reserve=reserve),
                ).run(rid)
        except LeaseLost as exc:
            return {"run_id": rid, "status": "locked", "detail": str(exc)}
        except SuperDocsError as exc:
            return {"run_id": rid, "status": "failed", "detail": str(exc)}
        report = build(ledger, outcome)

    return {
        "run_id": report["run_id"],
        "status": report["status"],
        "paused_at": report["paused_at"],
        "blocked_reason": report["blocked_reason"],
        "totals": report["totals"],
        "operations_remaining": report["totals"].get("account_operations_remaining"),
        "findings": report["findings"],
        "steps": [
            {"step_index": s["step_index"], "step_id": s["step_id"],
             "document": s["doc_slug"], "state": s["state"],
             "disposition": s["disposition"], "evidence": s["evidence"]}
            for s in report["steps"]
        ],
    }


@server.tool(
    description="Proposed changes waiting on a decision, with the before and after text "
                "for each. Call decide_changes to answer them."
)
def list_pending_changes(
    run_id: Annotated[str | None, Field(description="Defaults to the newest run.")] = None,
) -> dict[str, Any]:
    with _ledger() as ledger:
        rid = _resolve(ledger, run_id)
        pending = []
        for step in ledger.get_steps(rid):
            proposals = ledger.get_proposals(rid, step.step_index)
            decided = {d.change_id for d in ledger.get_decisions(rid, step.step_index)}
            waiting = [p.to_public() for p in proposals if p.change_id not in decided]
            if waiting:
                pending.append({
                    "step_index": step.step_index, "step_id": step.step_id,
                    "document": step.doc_slug, "changes": waiting,
                })
        return {"run_id": rid, "pending": pending}


@server.tool(
    description="Approve or reject proposed changes, one by one. Approving some and "
                "rejecting others in the same call is normal; a rejection never discards "
                "the rest. Decisions are durable immediately and survive a crash."
)
def decide_changes(
    step_index: Annotated[int, Field(description="Step the changes belong to.")],
    decisions: Annotated[
        list[dict[str, Any]],
        Field(description="[{change_id, approved: bool, feedback?: str}, ...]"),
    ],
    run_id: Annotated[str | None, Field(description="Defaults to the newest run.")] = None,
) -> dict[str, Any]:
    verdicts = {
        d["change_id"]: (bool(d["approved"]), d.get("feedback"))
        for d in decisions
    }
    with _ledger() as ledger:
        rid = _resolve(ledger, run_id)
        try:
            recorded = record_decisions(ledger, rid, step_index, verdicts, decided_by="mcp")
        except ValueError as exc:
            return {"error": str(exc)}
    return {
        "run_id": rid,
        "step_index": step_index,
        "approved": sum(1 for d in recorded if d.approved),
        "rejected": sum(1 for d in recorded if not d.approved),
        "next": "call advance_run to commit these and continue",
    }


@server.tool(
    description="Where the run stands, step by step, read from durable state. The resume "
                "point is whatever this reports; nothing is held in memory."
)
def run_status(
    run_id: Annotated[str | None, Field(description="Defaults to the newest run.")] = None,
) -> dict[str, Any]:
    with _ledger() as ledger:
        rid = _resolve(ledger, run_id)
        run = ledger.get_run(rid)
        steps = ledger.get_steps(rid)
        unfinished = [s for s in steps if s.state not in TERMINAL_STATES]
        return {
            "run_id": rid,
            "status": run.status if run else "unknown",
            "session_id": run.session_id if run else None,
            "resume_point": unfinished[0].step_index if unfinished else None,
            "steps": [
                {"step_index": s.step_index, "step_id": s.step_id,
                 "document": s.doc_slug, "state": s.state, "attempt": s.attempt,
                 "evidence": s.evidence, "billable_ops": s.billable_ops,
                 "duration_ms": s.duration_ms}
                for s in steps
            ],
        }
@server.tool(
    description="Export every document in the run to files. Exports never cost "
                "operations. Formats: docx, pdf, html, markdown, txt."
)
def export_run(
    out_dir: Annotated[str, Field(description="Directory to write into.")] = "out",
    fmt: Annotated[str, Field(description="docx | pdf | html | markdown | txt")] = "markdown",
    run_id: Annotated[str | None, Field(description="Defaults to the newest run.")] = None,
) -> dict[str, Any]:
    settings = load_settings()
    if not settings.api_key:
        return {"error": "SUPERDOCS_API_KEY is not set"}
    suffix = {"markdown": "md"}.get(fmt, fmt)
    written: list[str] = []
    with _ledger() as ledger:
        rid = _resolve(ledger, run_id)
        run = ledger.get_run(rid)
        if run is None:
            return {"error": f"no run {rid}"}
        target = Path(out_dir) / rid
        target.mkdir(parents=True, exist_ok=True)
        with SuperDocsClient(settings.api_key, settings.base_url) as client:
            for doc in ledger.get_documents(rid):
                if not doc.document_id:
                    continue
                blob = client.export_document(
                    run.session_id, doc.document_id, fmt=fmt
                )
                path = target / f"{doc.slug}.{suffix}"
                path.write_bytes(blob)
                written.append(str(path))
    return {"run_id": rid, "files": written}


@server.tool(
    description="Settle a step the runner refused to guess about. Reaching this means "
                "the evidence for whether the work landed was genuinely inconclusive, so "
                "a person must look at the document and say: 'done' if the work is "
                "there, 'replan' to run the step again."
)
def adjudicate_step(
    step_index: Annotated[int, Field(description="The step awaiting adjudication.")],
    resolve: Annotated[str, Field(description="'done' or 'replan'.")],
    run_id: Annotated[str | None, Field(description="Defaults to the newest run.")] = None,
) -> dict[str, Any]:
    if resolve not in ("done", "replan"):
        return {"error": "resolve must be 'done' or 'replan'"}
    with _ledger() as ledger:
        rid = _resolve(ledger, run_id)
        step = ledger.get_step(rid, step_index)
        if step.state not in (ADJUDICATE, FAILED):
            return {"error": f"step {step_index} is {step.state!r}, not awaiting adjudication"}
        ledger.transition(
            rid, step_index, expect=(ADJUDICATE, FAILED),
            to="done" if resolve == "done" else PLANNED,
            evidence=f"adjudicated by an operator: {resolve}",
            disposition=f"adjudicated: {resolve}",
        )
    return {"run_id": rid, "step_index": step_index, "resolved": resolve}


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="Longhaul MCP server")
    parser.add_argument("--spec", help="Default job spec for this server.")
    parser.add_argument("--transport", default="stdio",
                        choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()
    if args.spec:
        os.environ[_SPEC_ENV] = args.spec
    server.run(transport=args.transport)


if __name__ == "__main__":  # pragma: no cover
    main()
