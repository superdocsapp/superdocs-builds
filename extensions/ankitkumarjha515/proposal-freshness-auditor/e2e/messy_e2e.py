"""The messy run: real-world proposal chaos, not the happy path.

Every trap in this document is one real bid teams actually hit — the same
figure restated four different ways, a stale number in a heading, three stale
facts crammed into one sentence, a total row whose components must still add
up, a genuinely TRUE historical statement that must not be "corrected", a
contradiction inside the same document, and numbers that merely resemble the
stale one.

Run:  python e2e/messy_e2e.py [--max-ops 2]

One check here is EXPECTED TO FAIL. It documents a real limitation rather
than hiding it: see "table total vs components" below.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

from live_e2e import (  # noqa: E402
    Recorder,
    RecordingClient,
    _audit,
    load_key,
)
from freshness_auditor.apply import apply_batch  # noqa: E402
from freshness_auditor.ledger import FactLedger  # noqa: E402
from freshness_auditor.review import ReviewSession, build_batches  # noqa: E402
from freshness_auditor.verify import chunk_hashes, prove_surgical  # noqa: E402

MESSY = """<h1>Consolidated Capability Annex</h1>
<h2>1,200 staff supporting global operations</h2>
<p>Northwind Relief Alliance employs 1,200 permanent staff across 14 countries,
reaching 3.2 million beneficiaries each year.</p>
<p>Our workforce grew from 900 people in 2019 to 1,200 today, and we anticipate
1,200-1,500 within two years.</p>
<ul>
<li>Permanent staff: 1,200</li>
<li>Countries of operation: fourteen</li>
<li>Beneficiaries reached: 3.2m</li>
</ul>
<table>
<tr><th>Function</th><th>Headcount</th></tr>
<tr><td>Programme delivery</td><td>820</td></tr>
<tr><td>Logistics</td><td>240</td></tr>
<tr><td>Support services</td><td>140</td></tr>
<tr><td>Total permanent staff</td><td>1,200</td></tr>
</table>
<p>Asset register: 11,200 items tracked in total, including 1,200 laptops
distributed to field offices.</p>
<p>Section 14 of this annex records that we employed 1,200 staff as of 2023.</p>
<p>Elsewhere this annex states a headcount of 1,450, which contradicts the
figures above and should be reconciled before submission.</p>"""


def run(client: RecordingClient, rec: Recorder, ledger, max_ops: int) -> None:
    rec.scenario = "S6-messy"
    sid = f"e2e-messy-{int(time.time())}"

    rec.event("step", "Upload a deliberately messy annex")
    up = client.upload(sid, "annex.html", MESSY)
    parsed = up.get("html") or client.session_html(sid)
    before = client.session_html(sid)
    rec.event("info", f"{len(chunk_hashes(before))} chunks in the stored document")

    findings = _audit(parsed, "annex", ledger)
    head = [f for f in findings if f.fact_id == "headcount"]
    quotes = [f.evidence.quote for f in findings]
    sentences = " || ".join(f.evidence.sentence for f in findings)
    rec.event("info", f"{len(findings)} finding(s); headcount instances={len(head)}")
    rec.event("info", f"quotes={quotes}")

    # -- must find EVERY instance, not merely the first
    rec.check("finds MULTIPLE headcount instances, not just one", len(head) >= 4,
              ">=4 headcount findings (heading, prose, bullet, table total)",
              len(head),
              "the card says 'finds EVERY instance of a fact that has changed'. "
              "Fixing one and missing three leaves the proposal contradicting "
              "itself while the user believes it is done")

    # -- must not be fooled by lookalikes
    rec.check("did NOT match 11,200", not any("11,200" in q for q in quotes),
              "no finding quoting 11,200", quotes,
              "11,200 contains 1,200 as a substring; matching it would corrupt "
              "an unrelated asset figure")
    rec.check("did NOT flag the laptops sentence", "laptop" not in sentences.lower(),
              "no finding quoting laptops", sentences[:140],
              "same number, different subject — rewriting it is destructive")
    rec.check("did NOT flag the already-correct 1,450",
              not any(str(f.stated_value).replace(",", "") == "1450"
                      for f in findings),
              "no finding whose stated value is 1450",
              [f.stated_value for f in findings],
              "1,450 is already right; flagging it sends the user in circles")
    rec.check("did NOT treat 900 as a stale headcount",
              not any(str(f.stated_value).replace(",", "") == "900"
                      for f in findings),
              "no finding for 900", [f.stated_value for f in findings],
              "900 in 2019 is a true historical statement")
    rec.check("did NOT read 'Section 14' as a country count",
              not any(f.fact_id == "country_count" and "Section" in f.evidence.sentence
                      for f in findings),
              "no country_count finding quoting 'Section 14'", sentences[:140],
              "a section number is not a country count")

    # -- a TRUE statement about the past must not be confidently rewritten
    hist = [f for f in findings if "as of 2023" in f.evidence.sentence.lower()]
    if hist:
        rec.check("historical statement kept at low confidence",
                  all(f.confidence <= 0.75 for f in hist),
                  "confidence <= 0.75", [f.confidence for f in hist],
                  "'we employed 1,200 staff as of 2023' is TRUE; rewriting it "
                  "to 1,450 would make the document wrong")
    else:
        rec.event("info", "historical sentence not flagged at all — also acceptable")

    if not head:
        rec.event("warn", "no headcount findings; skipping the apply phase")
        return
    if max_ops < 1:
        rec.event("warn", "operation cap reached; skipping the apply phase")
        return

    session = ReviewSession.from_findings(findings)
    for f in head:
        session.approve(f.id)
    for f in findings:
        if f not in head:
            session.reject(f.id, note="out of scope for this batch")
    batches = build_batches(session)
    rec.check("all headcount fixes ride in ONE batch", len(batches) == 1,
              "exactly 1 batch", len(batches),
              "one operation should carry up to 25 corrections")
    if not batches:
        return

    rec.event("step", f"Correcting {len(head)} instances in one operation")
    res = apply_batch(client, batches[0], session_id=sid, timeout=420)
    rec.ops_observed += res.ops_charged
    after = client.session_html(sid)
    rec.event("info", f"proposed={res.proposed} approved={res.approved} "
                      f"rejected={res.rejected} ops={res.ops_charged}")
    if res.error:
        rec.event("fail", f"apply error: {res.error}")
    rec.event("info", f"'1,200' occurrences remaining: {after.count('1,200')}")

    # The server proposes ONE change per chunk, so several findings inside
    # one paragraph collapse into a single edit. Counting findings here
    # would be the wrong unit and would fail a correct run.
    target_chunks = {f.evidence.chunk_id for f in head if f.evidence.chunk_id}
    rec.event("info", f"{len(head)} findings across {len(target_chunks)} chunk(s)")
    rec.check("every affected section was corrected",
              res.approved >= len(target_chunks),
              f">={len(target_chunks)} changes applied (one per chunk)",
              res.approved,
              "a partial fix is worse than none: the document now contradicts "
              "itself and the user believes the job is done")
    rec.check("lookalike 11,200 survived untouched", "11,200" in after,
              "11,200 still present", "11,200" in after,
              "collateral damage to an unrelated figure")
    rec.check("laptops sentence survived untouched", "1,200 laptops" in after,
              "'1,200 laptops' still present", "1,200 laptops" in after,
              "collateral damage to a true sentence")

    # -- the trap nobody thinks about until it ships
    total_fixed = "1,450" in after
    components_intact = all(x in after for x in ("820", "240", "140"))
    rec.check("KNOWN GAP: table total vs its components",
              not (total_fixed and components_intact),
              "components updated too, or the inconsistency surfaced",
              f"total_updated={total_fixed} components_unchanged={components_intact}",
              "if the total reads 1,450 while the rows still sum to 1,200, the "
              "tool has produced an arithmetic contradiction a reviewer will "
              "catch. Recorded as a KNOWN GAP rather than hidden.",
              known_gap=True)

    proof = prove_surgical(before, after, list(batches[0].chunk_ids()))
    rec.event("info", proof.render().replace("\n", " | "))
    rec.check("no collateral damage across the messy document",
              proof.collateral == (), "no unintended chunk changed",
              proof.collateral,
              "the harder the document, the more this guarantee is worth")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-ops", type=int, default=2)
    args = ap.parse_args()

    rec = Recorder()
    ledger = FactLedger.load(ROOT / "fixtures" / "facts.yaml")
    client = RecordingClient(rec, api_key=load_key(), timeout=180)

    print("\n=== MESSY E2E — real-world proposal chaos ===\n", flush=True)
    try:
        run(client, rec, ledger, args.max_ops)
    except Exception as exc:
        import traceback
        rec.check("run completed without crashing", False, "no exception",
                  f"{type(exc).__name__}: {exc}",
                  "a crash mid-run can leave a document half-edited")
        traceback.print_exc()

    jpath, mpath = rec.write()
    passed = len(rec.checks) - len(rec.failed)
    print(f"\n=== RESULT: {passed}/{len(rec.checks)} checks passed, "
          f"{rec.ops_observed} operation(s) spent ===", flush=True)
    for c in rec.failed:
        print(f"  FAILED [{c['scenario']}] {c['name']}", flush=True)
    print(f"\nrecord: {jpath}\ntranscript: {mpath}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
