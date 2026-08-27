"""Live end-to-end demo against the real SuperDocs API.

Runs the three cases the card is graded on:

1. First run, draft a report from a range, review it, export .docx.
2. A figure moves, re-run and show that only that section changes, that the
   rest come out byte-identical, and that it costs zero operations.
3. A figure moves far enough to change the wording, re-run and show the model
   is called for exactly that one section.

Usage:  python scripts/demo.py [--keep]
Requires a key in SUPERDOCS_API_KEY or ~/.superdocs/agent_credentials.json.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import pathlib
import re
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from narrative_report.pipeline import NarrativeReportPipeline  # noqa: E402
from narrative_report.store import ReportStore  # noqa: E402
from narrative_report.superdocs import SuperDocsClient  # noqa: E402

SHEET = "FY24 P&L"
A1 = "B4:G12"

# Synthetic figures for a fictional company. Nothing real, per the brief.
DATA = [
    ["Line item", "Q1", "Q2", "Q3", "Q4", "FY total"],
    ["Subscription revenue", "$1,840,000", "$1,972,000", "$2,105,000", "$2,388,000", "$8,305,000"],
    ["Services revenue", "$412,000", "$388,000", "$455,000", "$401,000", "$1,656,000"],
    ["Cost of revenue", "(742,000)", "(768,000)", "(801,000)", "(884,000)", "(3,195,000)"],
    ["Sales & marketing", "(610,000)", "(655,000)", "(698,000)", "(742,000)", "(2,705,000)"],
    ["Research & development", "(488,000)", "(502,000)", "(534,000)", "(561,000)", "(2,085,000)"],
    ["Headcount", "84", "89", "94", "103", "103"],
    ["Net revenue retention", "108.4%", "111.2%", "109.7%", "114.3%", "114.3%"],
]


def banner(text: str) -> None:
    print(f"\n{'=' * 74}\n{text}\n{'=' * 74}")


def show(proposal) -> None:
    print(f"  revision {proposal.revision} | {proposal.plan_summary}")
    print(f"  operations spent : {proposal.operations_spent}")
    print(f"  narrative source : {proposal.narrative_source}")
    print("  stage timings    : " + ", ".join(
        f"{k}={v:.2f}s" for k, v in proposal.stage_seconds.items()
    ))
    if proposal.chart_url:
        print(f"  chart            : {proposal.chart_url}")
    for finding in proposal.findings:
        print(f"  ! {finding}")
    for section in proposal.sections:
        flag = "  " if not section.problems else " !"
        print(f"{flag} [{section.action:>13}] {section.heading}: {section.reason}")
        if section.action != "keep":
            text = re.sub(r"<[^>]+>", "", section.html)
            print(f"      {text[:250]}")
        for problem in section.problems:
            print(f"      PROBLEM: {problem}")


async def main(keep: bool) -> int:
    root = pathlib.Path(tempfile.mkdtemp(prefix="narrative-demo-"))
    store = ReportStore(root)
    # Unique per execution: the report id drives the SuperDocs session id, and a
    # session left paused by an earlier run refuses new instructions.
    report_id = f"demo-fy24-{int(time.time())}"

    async with SuperDocsClient() as client:
        before = await client.remaining_operations()
        print(f"operations remaining before demo: {before}")
        pipe = NarrativeReportPipeline(client, store)

        # ---------------------------------------------------------- first run
        banner("RUN 1, draft the report from the selected range")
        proposal = await pipe.propose(
            report_id=report_id, values=DATA, sheet=SHEET, a1=A1, title="FY24 performance review"
        )
        show(proposal)

        if proposal.blocking_problems:
            print("\n  A figure could not be traced to a cell. Refusing to commit.")
            return 1

        report, blob = await pipe.commit(report_id, {s.id: True for s in proposal.sections})
        out = root / "report-v1.docx"
        if blob:
            out.write_bytes(blob)
            print(f"\n  exported {len(blob):,} bytes -> {out}")
        for warning in report.export_warnings:
            print(f"  export warning: {warning}")

        v1 = {s.id: s.rendered for s in store.load_manifest(report_id).sections}

        # ------------------------------------------------- a figure moves a bit
        banner("RUN 2, Q4 subscription revenue restated, wording still holds")
        moved = copy.deepcopy(DATA)
        moved[1][4] = "$2,455,000"
        moved[1][5] = "$8,372,000"
        proposal2 = await pipe.propose(report_id=report_id, values=moved, sheet=SHEET, a1=A1)
        show(proposal2)

        untouched = [s for s in proposal2.sections if s.action == "keep"]
        identical = all(s.html == v1[s.id] for s in untouched)
        print(f"\n  untouched sections byte-identical: {identical} ({len(untouched)} section(s))")
        print(f"  operations spent on this update  : {proposal2.operations_spent}")
        await pipe.commit(report_id, {s.id: True for s in proposal2.sections})

        # ------------------------------------------- a figure moves a long way
        banner("RUN 3, Q4 subscription revenue collapses, wording must change")
        crashed = copy.deepcopy(DATA)
        crashed[1][4] = "$1,020,000"
        crashed[1][5] = "$6,937,000"
        proposal3 = await pipe.propose(report_id=report_id, values=crashed, sheet=SHEET, a1=A1)
        show(proposal3)
        print(f"\n  operations spent on this update: {proposal3.operations_spent}")

        report3, blob3 = await pipe.commit(
            report_id, {s.id: True for s in proposal3.sections}
        )
        if blob3:
            (root / "report-v3.docx").write_bytes(blob3)

        after = await client.remaining_operations()
        banner("SUMMARY")
        print(f"  operations used across all three runs: {before - after}")
        print(f"  artefacts: {root}")
        if not keep:
            print("  (pass --keep to leave the store in place)")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args().keep)))
