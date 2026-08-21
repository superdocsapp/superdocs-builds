"""Benchmark runner.

Two runs per case:

  control  upload -> export                     (no edit, 0 operations)
  edit     upload -> chat -> approve -> export  (1 operation)

The control is what makes the result attributable. Any difference the control
also shows is a property of ingest and export; only what the edit run adds is
caused by the edit. Without it a benchmark can say a table broke but not where.

Resumable: state is written after every case, so a killed run resumes without
re-spending operations on cases already measured.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback

from . import compare, extract
from .client import ApiError, BudgetExceeded, FakeClient, Ledger, SuperDocsClient
from .corpus import cases as case_mod
from .corpus.generate import write_docx

DEFAULT_OUT = "results"


def _load_state(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    return {"cases": {}, "ops_spent": 0, "started": time.time()}


def _save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, path)          # atomic: a crash mid-write cannot corrupt it


def run_case(case, client, workdir: str, mode: str = "dry") -> dict:
    """One case, both runs. Returns a result record.

    The record carries the mode it was produced in. A dry record and a
    live record are not interchangeable evidence, and nothing downstream
    is allowed to treat them as if they were.
    """
    src = write_docx(case, os.path.join(workdir, "corpus", f"{case.id}.docx"))
    before = extract.from_docx(src)
    rec: dict = {"id": case.id, "axis": case.axis, "title": case.title,
                 "mode": mode}
    t0 = time.monotonic()

    # ---- control: no edit -------------------------------------------------
    ctrl_findings: list[compare.Finding] = []
    ctrl_sid = f"tfb-{case.id}-control"
    try:
        client.upload(src, ctrl_sid)
        ctrl_out = client.export(
            ctrl_sid, os.path.join(workdir, "out", f"{case.id}.control.docx"))
        ctrl_findings = compare.compare(before, extract.from_docx(ctrl_out))
        rec["control"] = {"status": "ok",
                          "findings": [f.to_dict() for f in ctrl_findings]}
    except Exception as exc:                       # noqa: BLE001
        rec["control"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    # ---- edit run ---------------------------------------------------------
    sid = f"tfb-{case.id}-edit"
    try:
        html = client.upload(src, sid)
        html_doc = extract.from_html(html)
        ingest = compare.compare(before, html_doc, profile="html")
        rec["ingest_findings"] = [f.to_dict() for f in ingest]
        rec["ingest_unmeasurable"] = compare.unmeasurable_at_html_stage(
            compare.compare(before, html_doc))

        if hasattr(client, "simulate_edit"):
            client.simulate_edit(sid, case)
        job = client.edit(sid, html, case.edit)
        pending = job.get("pending") or []
        rec["proposed_changes"] = len(pending)
        if pending:
            client.approve(sid, job["job_id"], pending)

        out = client.export(sid, os.path.join(workdir, "out", f"{case.id}.edit.docx"))
        after = extract.from_docx(out)

        exempt = [case.target, *getattr(case, "also_changes", [])]
        findings = compare.compare(before, after, target=exempt)
        by_edit, by_round_trip = compare.attribute(findings, ctrl_findings)

        edit_applied = None
        if case.expect_contains is not None:
            tgt_tbl = after.tables[case.target[0]] if len(after.tables) > case.target[0] else None
            cell = tgt_tbl.cell_at(case.target[1], case.target[2]) if tgt_tbl else None
            haystack = _all_text(after)
            if cell is not None:
                edit_applied = case.expect_contains in _cell_text_deep(cell)
                if not edit_applied and case.expect_contains in haystack:
                    rec["note"] = ("expected value is present in the document "
                                   "but not in the target cell")
            else:
                # The cell we were told to check no longer exists. That is a
                # structural failure, not an unmeasurable one.
                edit_applied = False
                rec["note"] = "target cell absent from the exported grid"

        rec["findings"] = [f.to_dict() for f in findings]
        rec["caused_by_edit"] = [f.to_dict() for f in by_edit]
        rec["caused_by_round_trip"] = [f.to_dict() for f in by_round_trip]
        rec["edit_applied"] = edit_applied
        rec["verdict"] = compare.verdict(edit_applied, findings)
        rec["summary"] = compare.summarise(findings)
    except BudgetExceeded:
        raise
    except Exception as exc:                       # noqa: BLE001
        rec["verdict"] = compare.ERROR
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["traceback"] = traceback.format_exc(limit=3)

    rec["seconds"] = round(time.monotonic() - t0, 2)
    return rec


def _cell_text_deep(cell) -> str:
    """A cell's own text plus everything in tables nested inside it."""
    parts = [cell.text]
    for n in cell.nested:
        for c in n.cells:
            parts.append(_cell_text_deep(c))
    return "\n".join(parts)


def _all_text(doc) -> str:
    parts = list(doc.body_paragraphs)

    def walk(t):
        for c in t.cells:
            parts.append(c.text)
            for n in c.nested:
                walk(n)

    for t in doc.tables:
        walk(t)
    return "\n".join(parts)


def render_report(state: dict, ledger: Ledger, mode: str) -> str:
    recs = list(state["cases"].values())
    counts: dict[str, int] = {}
    for r in recs:
        counts[r.get("verdict", "?")] = counts.get(r.get("verdict", "?"), 0) + 1

    modes: dict[str, int] = {}
    for r in recs:
        modes[r.get("mode", "unknown")] = modes.get(r.get("mode", "unknown"), 0) + 1
    mixed = len(modes) > 1
    mode_line = (f"- mode: **{mode}**" if not mixed else
                 "- mode: **MIXED** - " +
                 ", ".join(f"{k}: {v} cases" for k, v in sorted(modes.items())))

    lines = [
        "# Table fidelity benchmark - results",
        "",
        mode_line,
        f"- cases run: **{len(recs)}**",
        f"- operations spent: **{ledger.spent}** (cap {ledger.cap})",
        "- verdicts: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        "",
    ] + ([
        "> **These results are not one run.** The records below were "
        "produced in more than one mode. A dry-mode record is a simulation "
        "and is not evidence about the live API. Use a separate `--out` "
        "directory per mode before quoting any of this.",
        "",
    ] if mixed else []) + [
        "Method: each case is uploaded, exported once with no edit (control), "
        "then uploaded, edited through one approval-gated instruction, "
        "approved and exported. Findings present in the control are attributed "
        "to the format round-trip; the remainder are attributed to the edit. "
        "The named target cell is exempt from content comparison; every other "
        "cell is an invariant.",
        "",
        "| case | mode | axis | verdict | edit applied | by edit | by round-trip | s |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(recs, key=lambda x: (x.get("axis", ""), x["id"])):
        applied = r.get("edit_applied")
        applied_s = {True: "yes", False: "no", None: "unverifiable"}.get(applied, "?")
        lines.append(
            f"| `{r['id']}` | {r.get('mode','?')} | {r.get('axis','')} | "
            f"{r.get('verdict','?')} | "
            f"{applied_s} | {len(r.get('caused_by_edit', []))} | "
            f"{len(r.get('caused_by_round_trip', []))} | {r.get('seconds','')} |"
        )

    lines += ["", "## Findings by case", ""]
    for r in sorted(recs, key=lambda x: x["id"]):
        if r.get("verdict") == compare.PASS and not r.get("caused_by_round_trip"):
            continue
        lines.append(f"### `{r['id']}` - {r.get('title','')}")
        if r.get("error"):
            lines.append(f"- run error: `{r['error']}`")
        for label, key in (("caused by the edit", "caused_by_edit"),
                           ("caused by the round-trip", "caused_by_round_trip")):
            items = r.get(key) or []
            if items:
                lines.append(f"- **{label}** ({len(items)}):")
                for f in items[:12]:
                    lines.append(
                        f"  - `{f['severity']}/{f['code']}` {f['where']} - "
                        f"expected `{f['expected'][:70]}`, got `{f['actual'][:70]}`")
                if len(items) > 12:
                    lines.append(f"  - ... and {len(items) - 12} more")
        if r.get("ingest_unmeasurable"):
            lines.append("- not measurable at the HTML stage: "
                         + ", ".join(f"`{c}`" for c in r["ingest_unmeasurable"]))
        if r.get("note"):
            lines.append(f"- note: {r['note']}")
        lines.append("")

    lines += ["## Timing by stage", ""]
    for stage, secs in sorted(ledger.timings.items()):
        lines.append(f"- {stage}: {secs:.1f}s")
    lines += ["", "## Limits of this measurement", "",
              "- Findings are reported against the exported DOCX. Attributes "
              "that plain HTML cannot express are withheld at the HTML stage "
              "and listed as not measurable rather than counted as losses.",
              "- A case whose run errored is reported ERROR, never FAIL. "
              "An unproven failure is not a failure.",
              "- Rendering is not compared. Two files that parse identically "
              "could still paginate differently; that is out of scope and "
              "stated rather than implied."]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tablebench")
    ap.add_argument("--mode", choices=("dry", "live"), default="dry",
                    help="dry runs entirely offline and spends nothing")
    ap.add_argument("--fault", default="none",
                    help="dry mode only: inject a named fidelity fault")
    ap.add_argument("--limit", type=int, default=None,
                    help="small-sample mode: run only the first N cases")
    ap.add_argument("--cases", default=None, help="comma-separated case ids")
    ap.add_argument("--axis", default=None, choices=case_mod.AXES)
    ap.add_argument("--max-ops", type=int, default=25,
                    help="hard operation cap; the run stops before exceeding it")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--resume", action="store_true",
                    help="skip cases already recorded in the state file")
    args = ap.parse_args(argv)

    selected = case_mod.select(
        ids=args.cases.split(",") if args.cases else None,
        axis=args.axis, limit=args.limit)
    if not selected:
        print("no cases selected", file=sys.stderr)
        return 2

    state_path = os.path.join(args.out, "state.json")
    state = _load_state(state_path) if args.resume else {
        "cases": {}, "ops_spent": 0, "started": time.time()}

    # Only spends made in THIS mode count against this cap. Simulated
    # operations from a dry run are not money and must not reserve budget.
    prior_spend = sum(r.get("ops", 0) for r in state.get("cases", {}).values()
                      if r.get("mode") == args.mode)
    ledger = Ledger(cap=args.max_ops, spent=prior_spend)
    if args.mode == "live":
        client = SuperDocsClient(ledger)
    else:
        client = FakeClient(ledger, fault=args.fault)

    print(f"mode={args.mode} cases={len(selected)} cap={args.max_ops} ops")
    if args.mode == "live":
        est = sum(1 for _ in selected)
        print(f"estimated spend: {est} operations "
              f"(1 per case; control and export are free)")

    stopped = None
    for case in selected:
        prior = state["cases"].get(case.id) if args.resume else None
        if prior is not None and prior.get("mode") == args.mode:
            print(f"  skip {case.id} (already recorded in {args.mode} mode)")
            continue
        if prior is not None:
            print(f"  rerun {case.id} (prior record was "
                  f"{prior.get('mode', 'unknown')} mode, not {args.mode})")
        spent_before = ledger.spent
        try:
            rec = run_case(case, client, args.out, mode=args.mode)
        except BudgetExceeded as exc:
            stopped = str(exc)
            print(f"  STOP {exc}")
            break
        rec["ops"] = ledger.spent - spent_before
        state["cases"][case.id] = rec
        state["ops_spent"] = ledger.spent
        _save_state(state_path, state)
        print(f"  {rec.get('verdict','?'):13s} {case.id:28s} "
              f"edit={len(rec.get('caused_by_edit', []))} "
              f"rt={len(rec.get('caused_by_round_trip', []))} "
              f"ops={ledger.spent}")

    if stopped:
        state["stopped_by_budget"] = stopped
        _save_state(state_path, state)

    report = render_report(state, ledger, args.mode)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "report.md"), "w") as fh:
        fh.write(report)
    print(f"\nreport: {os.path.join(args.out, 'report.md')}  "
          f"ops spent: {ledger.spent}/{ledger.cap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
