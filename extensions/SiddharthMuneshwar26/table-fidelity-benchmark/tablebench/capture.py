"""Capture evidence for a bug report.

Runs one case against the live API and writes everything a maintainer needs to
reproduce and locate the fault, without them having to install this benchmark:

    evidence/<case>/1-source.docx        what was uploaded
    evidence/<case>/2-ingest.html        the HTML your API returned  <-- the proof
    evidence/<case>/3-ingest-table.html  just the table, pretty-printed
    evidence/<case>/4-export.docx        what came back
    evidence/<case>/5-findings.txt       what differs, and at which stage
    evidence/<case>/6-summary.md         paste-ready bug report body

Why the HTML matters. For the merge bugs, the loss is visible in the response
from upload -- before any edit is requested. That locates the fault in the
ingest parser rather than the model or the export, which is the difference
between a report someone can act on and one they have to investigate first.

    python -m tablebench.capture --case merge_l_shaped --out evidence
    python -m tablebench.capture --case header_repeat_flag --out evidence

Costs one operation per case (the control run costs none, and --control-only
spends nothing at all).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys

from . import compare, extract
from .client import ApiError, Ledger, SuperDocsClient
from .corpus import cases as case_mod
from .corpus.generate import write_docx


def pretty_table(html: str) -> str:
    """Isolate the first table and indent it so a reader can see the spans."""
    m = re.search(r"<table\b.*?</table>", html, re.S | re.I)
    if not m:
        return "(no <table> element in the response)"
    frag = m.group(0)
    frag = re.sub(r"><", ">\n<", frag)
    out, depth = [], 0
    for line in frag.split("\n"):
        if re.match(r"</", line):
            depth = max(0, depth - 1)
        out.append("  " * depth + line)
        if re.match(r"<(table|tr|td|th|tbody|thead)\b", line) and not line.endswith("/>"):
            depth += 1
    return "\n".join(out)


def span_summary(html: str) -> str:
    """Count the spans the API's HTML actually carries."""
    rowspans = re.findall(r'rowspan="(\d+)"', html)
    colspans = re.findall(r'colspan="(\d+)"', html)
    return (f"rowspan attributes present: {len(rowspans)} {rowspans}\n"
            f"colspan attributes present: {len(colspans)} {colspans}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tablebench.capture")
    ap.add_argument("--case", required=True, choices=sorted(case_mod.BY_ID))
    ap.add_argument("--out", default="evidence")
    ap.add_argument("--control-only", action="store_true",
                    help="upload and export with no edit; spends no operations")
    ap.add_argument("--max-ops", type=int, default=2)
    a = ap.parse_args(argv)

    case = case_mod.BY_ID[a.case]
    outdir = os.path.join(a.out, a.case)
    os.makedirs(outdir, exist_ok=True)

    src = write_docx(case, os.path.join(outdir, "1-source.docx"))
    before = extract.from_docx(src)

    ledger = Ledger(cap=a.max_ops)
    try:
        client = SuperDocsClient(ledger)
    except ApiError as exc:
        print(exc, file=sys.stderr)
        return 2

    session = f"evidence-{a.case}"
    print(f"uploading {os.path.basename(src)} ...")
    html = client.upload(src, session)

    with open(os.path.join(outdir, "2-ingest.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    with open(os.path.join(outdir, "3-ingest-table.html"), "w",
              encoding="utf-8") as fh:
        fh.write(pretty_table(html))

    ingest_doc = extract.from_html(html)
    ingest_findings = compare.compare(before, ingest_doc, profile="html")

    if a.control_only:
        out_path = client.export(session, os.path.join(outdir, "4-export.docx"))
    else:
        print(f"sending one edit: {case.edit[:70]}...")
        job = client.edit(session, html, case.edit)
        if job.get("pending"):
            client.approve(session, job["job_id"], job["pending"])
        out_path = client.export(session, os.path.join(outdir, "4-export.docx"))

    after = extract.from_docx(out_path)
    exempt = [case.target, *getattr(case, "also_changes", [])]
    export_findings = compare.compare(before, after, target=exempt)

    lines = [
        f"CASE: {case.id} - {case.title}",
        f"AXIS: {case.axis}",
        "",
        "=== SOURCE (what was uploaded) ===",
        _grid(before.tables[0]) if before.tables else "(no table)",
        "",
        "=== AFTER INGEST (parsed from the HTML your API returned) ===",
        _grid(ingest_doc.tables[0]) if ingest_doc.tables else "(no table)",
        "",
        span_summary(html),
        "",
        f"--- differences at the INGEST stage: {len(ingest_findings)} ---",
    ]
    lines += [f"  {f}" for f in ingest_findings] or ["  (none)"]
    lines += ["", "=== AFTER EXPORT ===",
              _grid(after.tables[0]) if after.tables else "(no table)", "",
              f"--- differences in the EXPORTED file: {len(export_findings)} ---"]
    lines += [f"  {f}" for f in export_findings] or ["  (none)"]
    lines += ["", f"operations spent: {ledger.spent}"]

    report = "\n".join(lines)
    with open(os.path.join(outdir, "5-findings.txt"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print("\n" + report)

    # Attribute per finding, not per case. A single label was wrong on the
    # header-flag case: one unrelated ingest difference made the whole report
    # say "ingest" when the header marking actually survived ingest and was
    # lost on export -- the opposite of what the report needed to say.
    ingest_codes = {f.code for f in ingest_findings}
    export_codes = {f.code for f in export_findings}
    # Some attributes have no representation in plain HTML, so the HTML stage
    # withholds them. Withheld is not the same as intact: counting them as
    # "survived ingest" would assert something the evidence cannot support,
    # which is the exact failure this tool exists to avoid.
    withheld = sorted(export_codes & compare.HTML_UNREPRESENTABLE)
    lost_at_ingest = sorted(ingest_codes & export_codes)
    lost_at_export = sorted(export_codes - ingest_codes - set(withheld))

    if lost_at_ingest:
        stage = ("ingest -- present in the uploaded file, absent from the HTML "
                 "your API returned, before any edit was requested")
    elif lost_at_export:
        stage = ("export -- the HTML your API returned carries it correctly; "
                 "it is absent from the exported DOCX")
    elif withheld:
        stage = ("cannot be localised -- plain HTML has no property for "
                 "this, so the HTML stage cannot measure it either way")
    else:
        stage = "no difference found"
    with open(os.path.join(outdir, "6-summary.md"), "w", encoding="utf-8") as fh:
        fh.write(
            f"# {case.title}\n\n"
            f"**Where the loss happens:** {stage}\n\n"
            f"**What I did.** Uploaded `1-source.docx`"
            + ("" if a.control_only else f" and sent one instruction: "
                                         f"\"{case.edit}\"")
            + ", then exported.\n\n"
            f"**Files attached.** `1-source.docx` reproduces it. "
            f"`2-ingest.html` is the response from upload -- the loss is "
            f"visible there, before any edit. `4-export.docx` is what came "
            f"back. `5-findings.txt` lists every difference and the stage it "
            f"appeared at.\n\n"
            f"**Ingest differences:** {len(ingest_findings)}  \n"
            f"**Export differences:** {len(export_findings)}\n\n"
            + (f"**Lost at ingest:** {', '.join(lost_at_ingest)}\n\n"
               if lost_at_ingest else "")
            + (f"**Survives ingest, lost on export:** "
               f"{', '.join(lost_at_export)}\n\n" if lost_at_export else "")
            + (f"**Not measurable at the HTML stage** (no standard HTML "
               f"property, so this says nothing about where it was lost): "
               f"{', '.join(withheld)}\n" if withheld else ""))
    print(f"\nwritten to {outdir}/")
    return 0


def _grid(t) -> str:
    rows = []
    for c in sorted(t.cells, key=lambda c: (c.row, c.col)):
        flag = ""
        if c.row_span > 1 or c.col_span > 1:
            flag = f"  <-- rowspan={c.row_span} colspan={c.col_span}"
        rows.append(f"  ({c.row},{c.col}) {c.text[:26]!r}{flag}")
    return "\n".join(rows)


if __name__ == "__main__":
    sys.exit(main())
