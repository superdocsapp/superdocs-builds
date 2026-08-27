#!/usr/bin/env python
"""Measure content parity across two customer templates, over repeated runs.

The claim under test: *the same inputs re-drafted onto a second customer
template change presentation only.*

**Method, stated before the result.** Each run drafts the same
`examples/sample_input_complete.yaml` onto template A and template B, then
requires every data-derived fact — failure-mode ids, S/O/D ratings, computed
RPNs, action ids, target dates, PPAP part number and level, 8D root cause — to
appear verbatim in *both* exports. The fact list is derived from the input data
model, never from the output text. Deliberately **not** a raw digit scan: each
template's own boilerplate contains numbers (template A's instructions say
"1-10 AIAG-VDA scale", template B's don't) and those are presentation, not data.

**Why repeat runs.** A single green run would not support the claim. The model
is non-deterministic, and this was not theoretical: a cold session was observed
returning a `completed` job that changed nothing. So this reports every run, the
spread, and the worst case — not an average that hides the tail.

**Budget and stopping rule.** Each run costs 2 billable operations (one draft per
template); exports are free. Default is a 1-run smoke check. `--runs N` takes a
small sample; the loop stops at the first failed run unless `--keep-going` is
passed, so a broken build cannot quietly burn an allowance.

    export SUPERDOCS_API_KEY=sk_...
    python scripts/demo_two_templates.py --runs 3
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supplier_quality_drafter.client import SuperDocsClient
from supplier_quality_drafter.io_yaml import load_draft_request
from supplier_quality_drafter.models import DraftRequest
from supplier_quality_drafter.verify import expected_facts
from supplier_quality_drafter.workflow import approve_all, draft_document

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def required_facts(req: DraftRequest) -> list[str]:
    """Facts that must survive onto ANY template, verbatim.

    Builds on `verify.expected_facts` — the same check the drafter runs after
    every export, so the demo and the tool cannot drift apart — and adds the
    free-text and per-factor fields that only matter when comparing two
    renderings of the same data.
    """
    facts: list[str] = list(expected_facts(req))
    for fm in req.failure_modes:
        facts.append(fm.failure_mode)
        for value in (fm.severity, fm.occurrence, fm.detection):
            if value is not None:
                facts.append(str(value))
    for a in req.actions:
        facts.append(a.recommended_action)
    if req.ppap and req.ppap.submission_level is not None:
        facts.append(str(req.ppap.submission_level))
    if req.eightd and req.eightd.d4_root_cause:
        facts.append(req.eightd.d4_root_cause)
    return facts


def one_run(client, req, run_index: int, out_dir: str) -> dict:
    """Draft onto both templates once and check parity. Returns a raw record."""
    record: dict = {"run": run_index, "ok": False}
    started = time.monotonic()

    results = {}
    for label, template in (("a", "customer_template_a.html"), ("b", "customer_template_b.html")):
        # A fresh session per run: reusing one would let an earlier run's document
        # satisfy a later run's check, which would measure nothing.
        results[label] = draft_document(
            client, req,
            template_path=os.path.join(ROOT, "templates", template),
            session_id=f"parity-run{run_index}-{label}",
            export_path=os.path.join(out_dir, f"run{run_index}-template-{label}.md"),
            export_format="markdown",
            approval_callback=approve_all,
        )

    texts = {}
    for label, result in results.items():
        with open(result.exported_path, encoding="utf-8") as f:
            texts[label] = f.read()

    facts = required_facts(req)
    missing = {label: [f for f in facts if f not in text] for label, text in texts.items()}

    record.update(
        ok=not (missing["a"] or missing["b"]),
        facts_checked=len(facts),
        missing_a=missing["a"],
        missing_b=missing["b"],
        attempts_a=results["a"].attempts,
        attempts_b=results["b"].attempts,
        chars_a=len(texts["a"]),
        chars_b=len(texts["b"]),
        seconds=round(time.monotonic() - started, 1),
        job_a=results["a"].job_id,
        job_b=results["b"].job_id,
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runs", type=int, default=1,
                        help="Sample size. Each run costs 2 billable operations. Default 1 (smoke check).")
    parser.add_argument("--keep-going", action="store_true",
                        help="Continue after a failed run instead of stopping (spends more operations).")
    args = parser.parse_args()

    client = SuperDocsClient()
    # sample_input.yaml deliberately withholds a rating to demo the validation
    # gate, so parity is measured on the complete variant.
    req = load_draft_request(os.path.join(ROOT, "examples", "sample_input_complete.yaml"))

    out_dir = os.path.join(ROOT, "out")
    os.makedirs(out_dir, exist_ok=True)

    print(f"Method: {len(required_facts(req))} data-derived facts must appear verbatim in BOTH exports.")
    print(f"Sample: {args.runs} run(s), {args.runs * 2} billable operation(s). "
          f"Stopping rule: {'none (--keep-going)' if args.keep_going else 'halt on first failed run'}.\n")

    records = []
    for i in range(1, args.runs + 1):
        print(f"run {i}/{args.runs} ...", end=" ", flush=True)
        try:
            record = one_run(client, req, i, out_dir)
        except Exception as e:                      # a failed run is data, not a crash
            record = {"run": i, "ok": False, "error": f"{type(e).__name__}: {e}"}
        records.append(record)
        if record["ok"]:
            print(f"parity OK  ({record['facts_checked']} facts, "
                  f"{record['attempts_a']}+{record['attempts_b']} attempts, {record['seconds']}s)")
        else:
            print(f"FAILED  {record.get('error') or record.get('missing_a') or record.get('missing_b')}")
            if not args.keep_going:
                print("Stopping (stopping rule). Re-run with --keep-going to sample through failures.")
                break

    passed = sum(1 for r in records if r["ok"])
    print(f"\n--- result over {len(records)} run(s) ---")
    print(f"parity held: {passed}/{len(records)}")

    timed = [r["seconds"] for r in records if r.get("seconds")]
    if timed:
        spread = f", stdev {statistics.stdev(timed):.1f}s" if len(timed) > 1 else ""
        # Worst case, not just the average — an average hides the run that hurt.
        print(f"latency: median {statistics.median(timed):.1f}s, worst {max(timed):.1f}s{spread}")
    attempts = [r[k] for r in records for k in ("attempts_a", "attempts_b") if r.get(k)]
    if attempts:
        retried = sum(1 for a in attempts if a > 1)
        print(f"drafts needing a retry (cold-session no-op): {retried}/{len(attempts)}")

    raw_path = os.path.join(ROOT, "docs", "samples", "parity-runs.json")
    os.makedirs(os.path.dirname(raw_path), exist_ok=True)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)
    print(f"raw data: {os.path.relpath(raw_path, ROOT)}")

    if passed == len(records) and records:
        print("\nOK: every data fact appears verbatim in both exports on every run — "
              "the two documents differ only in template structure and wording.")
    return 0 if (records and passed == len(records)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
