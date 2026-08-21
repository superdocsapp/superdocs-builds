"""Build the review document, then put it through SuperDocs.

Every figure in the output is placed here, by this file, from parsed rows. The
model is asked only to write the narrative around figures already fixed, and is
told so in the instruction. That is the difference between a summary an
underwriter can act on and one they have to re-check.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import html
import json
import os
import sys

from . import parse, summarize
from .model import Summary
from .superdocs import (ApiError, BudgetExceeded, FakeClient, Ledger,
                        SearchUnavailable, SuperDocsClient)

PLACEHOLDER = "[[CORRESPONDENCE]]"

# What the prose documents are asked. Arithmetic over the loss runs cannot find
# any of these: each lives in a sentence in a note, an application or an email.
PROSE_QUERIES = [
    "any claim reopened after being shown as closed, and the reserve "
    "re-established for it",
    "any reserve increased after a suit was filed, and the stated reserve "
    "history",
    "any statement that a loss run was reissued or superseded, and which "
    "version should be relied on",
]


def money(v: float) -> str:
    return f"{v:,.2f}"


def build_html(s: Summary, prose: list[dict], as_of: datetime.date) -> str:
    p: list[str] = []
    e = html.escape

    p.append(f"<h1>Loss run review — {e(s.insured)}</h1>")
    p.append(f"<p>Prepared {as_of.isoformat()}. Figures are read from the loss "
             f"runs listed at the foot of this document and totalled "
             f"arithmetically. No figure in this review is model-generated.</p>")

    p.append("<h2>Summary by policy year</h2>")
    p.append("<table><tr><th>Policy year</th><th>Policy</th><th>Claims</th>"
             "<th>Open</th><th>Paid</th><th>Reserve</th><th>Incurred</th>"
             "<th>Loss ratio</th><th>Source</th></tr>")
    for y in s.years:
        lr = f"{y.loss_ratio:.1%}" if y.loss_ratio is not None else "not available"
        flag = " ***" if y.loss_ratio and y.loss_ratio > 0.60 else ""
        p.append(
            f"<tr><td>{y.policy_year}</td><td>{e(y.policy_no)}</td>"
            f"<td>{y.claim_count}</td><td>{y.open_count}</td>"
            f"<td>{money(y.total_paid)}</td><td>{money(y.total_reserve)}</td>"
            f"<td>{money(y.total_incurred)}</td><td>{lr}{flag}</td>"
            f"<td>{e(y.source)}</td></tr>")
    p.append(f"<tr><td><b>Total</b></td><td></td><td><b>{s.total_claims}</b></td>"
             f"<td><b>{s.total_open}</b></td><td></td><td></td>"
             f"<td><b>{money(s.total_incurred)}</b></td><td></td><td></td></tr>")
    p.append("</table>")

    p.append("<h2>Open claims</h2>")
    if not s.open_claims:
        p.append("<p>No claim is open across the policy years reviewed.</p>")
    else:
        p.append(f"<p>{len(s.open_claims)} claims remain open, carrying "
                 f"{money(sum(c.incurred for c in s.open_claims))} incurred. "
                 f"Listed separately from closed claims because reserves on "
                 f"open claims may still develop.</p>")
        p.append("<table><tr><th>Claim</th><th>PY</th><th>Coverage</th>"
                 "<th>Date of loss</th><th>Paid</th><th>Reserve</th>"
                 "<th>Incurred</th><th>Months open</th></tr>")
        for c in s.open_claims:
            p.append(f"<tr><td>{e(c.claim_no)}</td><td>{c.policy_year}</td>"
                     f"<td>{e(c.coverage)}</td><td>{e(c.date_of_loss)}</td>"
                     f"<td>{money(c.paid)}</td><td>{money(c.reserve)}</td>"
                     f"<td>{money(c.incurred)}</td>"
                     f"<td>{c.months_open(as_of)}</td></tr>")
        p.append("</table>")

    p.append("<h2>Conflicts between sources</h2>")
    if not s.conflicts:
        p.append("<p>The sources agree. No conflict found.</p>")
    else:
        p.append("<p>Surfaced, not resolved. Each needs a decision before the "
                 "figures above are relied on.</p>")
        for c in s.conflicts:
            p.append(f"<p><b>{e(c.subject)}</b> — {e(c.left)} versus "
                     f"{e(c.right)}. {e(c.detail)}"
                     + (f" {e(c.consequence)}" if c.consequence else "") + "</p>")

    p.append("<h2>Checklist findings</h2>")
    if not s.findings:
        p.append("<p>Every rule was applied and none fired. No findings.</p>")
    else:
        p.append("<table><tr><th>Rule</th><th>Subject</th><th>Finding</th>"
                 "<th>Source</th></tr>")
        for f in s.findings:
            p.append(f"<tr><td>{e(f.rule)}</td><td>{e(f.subject)}</td>"
                     f"<td>{e(f.title)}: {e(f.detail)}</td>"
                     f"<td>{e(f.source)}</td></tr>")
        p.append("</table>")

    if prose is not None:
        p.append("<h2>From the correspondence and adjuster notes</h2>")
        p.append("<p>Read from the non-tabular documents attached to this "
                 "review. Quoted context only; no figure below is used in any "
                 "total above.</p>")
        if prose:
            for hit in prose[:6]:
                snippet = " ".join(hit.get("text", "").split())[:320]
                p.append(f"<p><i>{e(hit.get('document', ''))}</i> — "
                         f"{e(snippet)}</p>")
        else:
            p.append(f"<p>{PLACEHOLDER}</p>")

    p.append("<h2>What this review does not establish</h2>")
    items = list(s.unverified)
    items.append("Figures are as stated by the carrier. This review checks each "
                 "loss run against itself and against the others; it cannot "
                 "confirm the carrier's own numbers.")
    if s.documents_superseded:
        items.append("Superseded documents were read and compared but are not "
                     "counted in any total: "
                     + ", ".join(s.documents_superseded) + ".")
    p.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in items) + "</ul>")

    p.append("<h2>Sources</h2><ul>"
             + "".join(f"<li>{e(d)}</li>" for d in s.documents_read) + "</ul>")
    return "\n".join(p)


def build_instruction(queries: list[str]) -> str:
    """One instruction, two edits, one operation.

    An earlier version asked for a JSON chat reply and looked for it in the
    proposed-changes payload, which carries document edits and not chat text.
    That was fighting the product: this is an editing agent, so the answer
    belongs in the document. Asking it to fill a placeholder section is both
    the supported path and half the cost.
    """
    asks = "\n".join(f"   - {q}" for q in queries)
    return (
        f"Make exactly two edits to this document, grounded only in the files "
        f"attached to this session.\n\n"
        f"1. Replace the placeholder text {PLACEHOLDER} with a short list of "
        f"what the attached adjuster notes, application and correspondence say "
        f"about:\n{asks}\n"
        f"   Name the source document for each point and quote at most one "
        f"sentence from it. Where the attached documents do not answer one of "
        f"these, say so for that point rather than inferring an answer.\n\n"
        f"2. Add an opening paragraph directly under the title, of at most four "
        f"sentences, summarising this account for an underwriter who has not "
        f"seen it.\n\n"
        f"Every number, date, claim number and table cell in this document has "
        f"been calculated from source records and is already correct: do not "
        f"change, recalculate, round or restate any of them. If text you write "
        f"would need a number, refer to the table instead of repeating it. Do "
        f"not add a recommendation on whether to write the risk. Change nothing "
        f"else."
    )


# Kept as a name for the tests that assert the figures are protected.
NARRATIVE_INSTRUCTION = build_instruction(PROSE_QUERIES)


def run(corpus_dir: str, out_dir: str, mode: str, max_ops: int,
        as_of: datetime.date, skip_prose: bool = False) -> dict:
    runs_paths = sorted(glob.glob(os.path.join(corpus_dir, "loss-runs", "*.csv")))
    runs_paths += sorted(glob.glob(os.path.join(corpus_dir, "loss-runs", "*.pdf")))
    if not runs_paths:
        raise SystemExit(f"no loss runs found under {corpus_dir}/loss-runs/")

    runs, unreadable = [], []
    for path in runs_paths:
        try:
            runs.append(parse.load(path))
        except (ValueError, OSError) as exc:
            unreadable.append(f"{os.path.basename(path)}: {exc}")

    # The same policy year may arrive as both CSV and PDF. Prefer the CSV, and
    # use the PDF as a cross-check rather than a second opinion in the totals.
    seen, deduped, crosschecks = {}, [], []
    for r in runs:
        key = (r.policy_year, r.valuation_date, r.is_reissue)
        if key in seen:
            other = seen[key]
            same = (len(r.claims) == len(other.claims)
                    and abs(r.summed_total - other.summed_total) < 0.01)
            crosschecks.append(
                f"{os.path.basename(r.path)} and {os.path.basename(other.path)} "
                f"cover the same valuation and "
                + ("agree." if same else
                   f"DISAGREE: {r.summed_total:,.2f} vs {other.summed_total:,.2f}."))
            continue
        seen[key] = r
        deduped.append(r)

    insured = "the insured"
    app_path = glob.glob(os.path.join(corpus_dir, "application", "*.docx"))
    app_text = parse.docx_text(app_path[0]) if app_path else ""
    for r in deduped:
        pass

    notes = {}
    for p in glob.glob(os.path.join(corpus_dir, "adjuster-notes", "*.docx")):
        base = os.path.basename(p)
        notes[base.split("-adjuster")[0]] = parse.docx_text(p)

    s = summarize.summarise(deduped, insured)
    s = summarize.examine(s, deduped, notes, app_text, as_of=as_of)
    s.unverified.extend(crosschecks)
    for u in unreadable:
        s.unverified.append(f"Could not read {u}")

    ledger = Ledger(cap=max_ops)
    corpus_text = dict(notes)
    if app_text:
        corpus_text["renewal application"] = app_text
    for p in glob.glob(os.path.join(corpus_dir, "correspondence", "*.docx")):
        corpus_text[os.path.basename(p)] = parse.docx_text(p)

    client = (SuperDocsClient(ledger) if mode == "live"
              else FakeClient(ledger, corpus_text))

    session = f"lossrun-{as_of.isoformat()}"

    # Uploads are free, and attaching the prose documents to the session is
    # what makes cross-document retrieval possible at all. Do it before asking.
    prose_docs = sorted(
        p for p in glob.glob(os.path.join(corpus_dir, "**", "*.docx"),
                             recursive=True))
    for p in prose_docs:
        try:
            client.upload(p, session)
        except (ApiError, OSError) as exc:
            s.unverified.append(f"Could not attach {os.path.basename(p)}: {exc}")

    # None means the section is not wanted at all; [] means it is wanted and
    # will be filled in the document by the edit below.
    prose: list[dict] | None = None if skip_prose else []
    doc_html = build_html(s, prose, as_of)
    instruction = (build_instruction(PROSE_QUERIES) if not skip_prose
                   else build_instruction([]))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "review.html"), "w", encoding="utf-8") as fh:
        fh.write(doc_html)
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(s.to_dict(), fh, indent=2)

    exported = None
    try:
        job = client.edit(session, doc_html, instruction)
        pending = job.get("pending") or []
        if pending:
            client.approve(session, job["job_id"], pending)
        else:
            s.unverified.append(
                "The narrative edit proposed no changes, so the correspondence "
                "section still holds its placeholder and no opening paragraph "
                "was added. Every figure above is unaffected.")
        exported = client.export(
            session, os.path.join(out_dir, "loss-run-review.docx"))
    except BudgetExceeded as exc:
        s.unverified.append(f"Stopped at the operation cap: {exc}")
    except (ApiError, OSError) as exc:
        s.unverified.append(f"Document assembly did not complete: {exc}")

    return {"summary": s, "ledger": ledger, "html": doc_html,
            "exported": exported, "out_dir": out_dir}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lossrun")
    ap.add_argument("--corpus", default="corpus/out")
    ap.add_argument("--out", default="out")
    ap.add_argument("--mode", choices=("dry", "live"), default="dry")
    ap.add_argument("--max-ops", type=int, default=6,
                    help="hard cap; the run stops before exceeding it")
    ap.add_argument("--as-of", default=None,
                    help="valuation date for ageing rules (YYYY-MM-DD)")
    ap.add_argument("--skip-prose", action="store_true",
                    help="skip the search stage and spend nothing on it")
    a = ap.parse_args(argv)

    as_of = (datetime.date.fromisoformat(a.as_of) if a.as_of
             else datetime.date.today())
    r = run(a.corpus, a.out, a.mode, a.max_ops, as_of, a.skip_prose)
    s, led = r["summary"], r["ledger"]

    print(f"mode={a.mode}  documents read={len(s.documents_read)}  "
          f"superseded={len(s.documents_superseded)}")
    for y in s.years:
        lr = f"{y.loss_ratio:.1%}" if y.loss_ratio is not None else "n/a"
        print(f"  PY{y.policy_year}  claims={y.claim_count:3d} "
              f"open={y.open_count:2d}  incurred={y.total_incurred:>13,.2f}  "
              f"LR={lr:>7}")
    print(f"  TOTAL claims={s.total_claims} open={s.total_open} "
          f"incurred={s.total_incurred:,.2f}")
    print(f"  conflicts={len(s.conflicts)}  findings={len(s.findings)}  "
          f"unverified={len(s.unverified)}")
    print(f"  operations spent={led.spent}/{led.cap}  {led.by_stage}")
    print(f"  written to {r['out_dir']}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
