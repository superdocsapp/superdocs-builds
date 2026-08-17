"""The cross-customer leakage test.

Northwind's 5 documents, then Ember's 5, memory-on throughout, each client
scoped by its own `cross_session_memory_key` — the only isolation primitive
this design uses (see PROGRESS.md, 2026-08-13, for the schema citation and
live probe behind that choice; `cross_session_search` is never enabled).

Protocol per document, per client: identical in shape to the main
measurement's memory-on arm (agent edit -> checker score against that
client's OWN rubric -> one scripted correction round -> re-score), so the
correction round is what teaches each client's house style into its own
memory_key. After both clients have run, EVERY final document is scanned for
the OPPOSING client's STRONG leak fingerprints — the axes classified as having
no plausible base-model-default explanation (see rubrics/northwind.json and
rubrics/ember.json, "leak_fingerprints").

Known limitation, found and corrected for before the live run, not discovered
after: seed content is reused from corpus/normalized/ (real generated prose,
zero MERIDIAN violations). That prose was generated under Meridian's OWN
conventions — day-first dates (H6) and "you" addressing the reader (H14) —
and both of those ALREADY match a strong fingerprint on one side: Ember's
strong L7 ("you"/"your") and Northwind's strong L6 (day-first dates) are both
present in the raw, unedited seed, confirmed by scanning it before any live
call was made. A naive final-document scan would misattribute any residual,
imperfectly-corrected instance of "you" or a day-first date to a cross-session
memory leak, when it could just be the client's OWN correction round failing
to convert every instance (each correction message quotes and fixes ONE
instance per rule, not every occurrence in the document).

Fix: every seed document is ALSO scanned for both fingerprint sets before any
editing, and the reported contamination metric is the INCREASE over that
seed baseline (floored at 0), not the raw final count. Raw final counts are
still reported alongside, for transparency, but the increase-over-baseline is
the number the leak claim rests on.

No noise-floor pass (memory OFF on this same 5-document leak corpus, run live
end to end) was performed in this session — the operator's 5-stage plan did
not include it. The seed-baseline subtraction above is a weaker, static
substitute for that: it removes fingerprint hits already present before any
agent touched the text, but it is not the same as a live memory-off arm on
these exact documents. Flagged, not silently upgraded to "noise floor
established."
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import config
from checker.h3 import GeminiH3Provider, MockH3Provider
from checker.score import load_rubric, score_document
from corrections.generator import (H3Cache, _CachedH3Provider,
                                   corrections_from_score, load_templates)
from superdocs.client import SuperDocsClient
from superdocs.mcp_transport import MCPHttpTransport
from runner.experiment import GENERIC_INSTRUCTION

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "corpus" / "normalized"
CLIENTS = {"northwind": "leak_northwind", "ember": "leak_ember"}


@dataclass
class LeakDocumentRun:
    document: str
    client: str
    session_id: str
    edit_ops_charged: int
    score_before_own_rubric: dict
    corrections_sent: int
    correction_ops_charged: int
    final_text: str


@dataclass
class ClientLeakResult:
    client: str
    memory_key: str
    wipe_removed: int
    documents: list[LeakDocumentRun] = field(default_factory=list)

    @property
    def total_ops(self) -> int:
        return sum(d.edit_ops_charged + d.correction_ops_charged
                   for d in self.documents)


def run_client(client_name: str, client: SuperDocsClient, rubric: dict,
              templates: dict, seed_docs: list[Path], log=print
              ) -> ClientLeakResult:
    key = CLIENTS[client_name]
    removed = client.clear_cross_session_memory(key)
    log(f"  wiped {key!r}: removed={removed} (expected 0, never used before)")
    result = ClientLeakResult(client=client_name, memory_key=key,
                              wipe_removed=removed)

    for doc_path in seed_docs:
        session = client.init_session()
        client.upload_document(session, doc_path.name, doc_path.read_bytes())

        edit = client.chat_with_retry(
            session, GENERIC_INSTRUCTION, attempts=3, backoff=2,
            approval_mode="approve_all", cross_session_memory=True,
            cross_session_memory_key=key, cross_session_search=False)

        text = client.export_document(session, "markdown")
        score = score_document(text, rubric, MockH3Provider())  # no LLM rules
        corr = corrections_from_score(score, templates)

        correction_charged = 0
        if corr.corrections:
            correction = client.chat_with_retry(
                session, corr.payload, attempts=3, backoff=2,
                approval_mode="approve_all", cross_session_memory=True,
                cross_session_memory_key=key, cross_session_search=False)
            correction_charged = correction.ops_charged
            text = client.export_document(session, "markdown")

        run = LeakDocumentRun(
            document=doc_path.name, client=client_name, session_id=session,
            edit_ops_charged=edit.ops_charged,
            score_before_own_rubric=score.as_dict(),
            corrections_sent=len(corr.corrections),
            correction_ops_charged=correction_charged, final_text=text)
        result.documents.append(run)
        log(f"    {doc_path.name}: own-rubric before={score.total_raw} "
           f"corrections_sent={len(corr.corrections)} "
           f"ops={run.edit_ops_charged + correction_charged}")
    return result


def scan_fingerprints(text: str, fingerprints: dict) -> dict[str, dict[str, int]]:
    """axis -> count, per strength tier. Counts, not just presence, so a
    baseline subtraction can be exact rather than boolean."""
    out: dict[str, dict[str, int]] = {"strong": {}, "medium": {}, "weak": {}}
    for strength in ("strong", "medium", "weak"):
        for fp in fingerprints.get(strength, []):
            pattern = fp.get("pattern")
            if not pattern:
                continue  # "medium"/"weak" entries here are qualitative only
                          # (no regex); nothing to scan.
            axis = fp.get("axis") or pattern[:20]
            n = len(re.findall(pattern, text, re.IGNORECASE))
            if n:
                out[strength][axis] = out[strength].get(axis, 0) + n
    return out


def net_over_baseline(final: dict, baseline: dict) -> dict:
    """final counts minus seed-baseline counts, floored at 0, per axis."""
    out: dict[str, dict[str, int]] = {}
    for strength in ("strong", "medium", "weak"):
        out[strength] = {}
        for axis, n in final.get(strength, {}).items():
            net = max(0, n - baseline.get(strength, {}).get(axis, 0))
            if net:
                out[strength][axis] = net
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--run-dir", type=str, default="runs/leak_test")
    args = ap.parse_args(argv)

    seed_docs = sorted(SEED_DIR.glob("doc_*.md"))[:args.n]
    if len(seed_docs) < args.n:
        print(f"only {len(seed_docs)} seed documents available",
             file=sys.stderr)
        return 2

    northwind = load_rubric("northwind")
    ember = load_rubric("ember")
    templates = load_templates()
    run_dir = ROOT / args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    client = SuperDocsClient(MCPHttpTransport())

    print(f"=== Northwind ({len(seed_docs)} documents) ===")
    nw_result = run_client("northwind", client, northwind, templates,
                           seed_docs)
    print(f"\n=== Ember ({len(seed_docs)} documents) ===")
    em_result = run_client("ember", client, ember, templates, seed_docs)

    print("\n=== seed baseline (scanned before any live call) ===")
    nw_fp = northwind["leak_fingerprints"]
    em_fp = ember["leak_fingerprints"]
    seed_baseline_nw = {d.name: scan_fingerprints(d.read_text("utf-8"), nw_fp)
                        for d in seed_docs}
    seed_baseline_em = {d.name: scan_fingerprints(d.read_text("utf-8"), em_fp)
                        for d in seed_docs}
    for d in seed_docs:
        print(f"  {d.name}: northwind-fp {seed_baseline_nw[d.name]['strong']}"
             f"  ember-fp {seed_baseline_em[d.name]['strong']}")

    print("\n=== fingerprint scan: final documents vs seed baseline ===")
    # Did EMBER's output pick up NORTHWIND's markers, beyond what the seed
    # already had? (seed_baseline_nw indexed by document name — same 5 files
    # used for both clients, so this is a same-document comparison.)
    ember_contamination = []
    for d in em_result.documents:
        final = scan_fingerprints(d.final_text, nw_fp)
        baseline = seed_baseline_nw[d.document]
        ember_contamination.append({"document": d.document, "final": final,
                                    "seed_baseline": baseline,
                                    "net": net_over_baseline(final, baseline)})
    # Did NORTHWIND's output pick up EMBER's markers, beyond baseline?
    northwind_contamination = []
    for d in nw_result.documents:
        final = scan_fingerprints(d.final_text, em_fp)
        baseline = seed_baseline_em[d.document]
        northwind_contamination.append({"document": d.document, "final": final,
                                        "seed_baseline": baseline,
                                        "net": net_over_baseline(final, baseline)})

    def strong_total(contamination, key="net"):
        return sum(sum(d[key]["strong"].values()) for d in contamination)

    print(f"Northwind markers found in Ember's output, NET of seed baseline "
         f"(strong): {strong_total(ember_contamination)}"
         f"  (raw final, unadjusted: {strong_total(ember_contamination, 'final')})")
    print(f"Ember markers found in Northwind's output, NET of seed baseline "
         f"(strong): {strong_total(northwind_contamination)}"
         f"  (raw final, unadjusted: {strong_total(northwind_contamination, 'final')})")

    out = {
        "seed_documents": [d.name for d in seed_docs],
        "northwind": {"memory_key": nw_result.memory_key,
                      "wipe_removed": nw_result.wipe_removed,
                      "total_ops": nw_result.total_ops,
                      "documents": [asdict(d) for d in nw_result.documents]},
        "ember": {"memory_key": em_result.memory_key,
                 "wipe_removed": em_result.wipe_removed,
                 "total_ops": em_result.total_ops,
                 "documents": [asdict(d) for d in em_result.documents]},
        "seed_baseline": {"northwind_fingerprints": seed_baseline_nw,
                         "ember_fingerprints": seed_baseline_em},
        "contamination": {
            "northwind_markers_in_ember_output": ember_contamination,
            "ember_markers_in_northwind_output": northwind_contamination,
            "strong_hit_totals_net_of_baseline": {
                "northwind_into_ember": strong_total(ember_contamination),
                "ember_into_northwind": strong_total(northwind_contamination),
            },
            "strong_hit_totals_raw_unadjusted": {
                "northwind_into_ember": strong_total(ember_contamination, "final"),
                "ember_into_northwind": strong_total(northwind_contamination, "final"),
            },
        },
        "limitation": ("Seed prose was generated under MERIDIAN's own "
                       "conventions (day-first dates, 'you' addressing the "
                       "reader), which pre-existed as hits on Northwind's L6 "
                       "and Ember's L7 strong fingerprints BEFORE any live "
                       "call was made — confirmed by scanning the seed before "
                       "this run. The headline metric is therefore net-of-"
                       "seed-baseline, not the raw final count. This is a "
                       "static baseline, not a live memory-off noise-floor "
                       "pass on these documents — the operator's 5-stage plan "
                       "did not include running the leak corpus memory-off; "
                       "flagged rather than silently upgraded."),
        "ledger": client.ledger.as_dict(),
    }
    out_path = run_dir / "results.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwritten: {out_path}")
    print(f"total SuperDocs operations spent: {client.ledger.total_operations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
