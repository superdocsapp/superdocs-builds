"""Orchestrator: dry-run inventory + full reconcile."""

from __future__ import annotations

from pathlib import Path

import report

from .classify import build_coverage, classify, detect_conflicts
from .common import client, list_docx, write_json
from .drafts import draft_merges
from .extract import extract
from .ingest import ingest
from .match import match


def dry_run_inventory(estate_a, estate_b, output, limit=None):
    docs = []
    for estate, folder in (("a", estate_a), ("b", estate_b)):
        for path in list_docx(folder, limit=limit):
            docs.append(
                {
                    "estate": estate,
                    "filename": path.name,
                    "stem": path.stem,
                    "path": str(path.resolve()),
                }
            )
    payload = {
        "dry_run": True,
        "note": "No SuperDocs calls were made. Content-based matching did NOT run.",
        "documents_a": sum(1 for d in docs if d["estate"] == "a"),
        "documents_b": sum(1 for d in docs if d["estate"] == "b"),
        "docs": docs,
        "would_run": [
            "upload both estates into one compare session (tabs)",
            "extract obligations per document via chat_async (core)",
            "match + classify via chat_async (core)",
            "detect conflicts locally from verbatim excerpts",
            "draft merges via chat_async HITL (pro, ask_every_time)",
        ],
    }
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "dry_run.json", payload)
    mapping = {"policies": []}
    conflicts = {"conflicts": []}
    coverage = {
        "totals": {
            "documents_a": payload["documents_a"],
            "documents_b": payload["documents_b"],
            "documents_total": payload["documents_a"] + payload["documents_b"],
            "obligations_a": 0,
            "obligations_b": 0,
            "obligations_total": 0,
            "mapped": 0,
            "gap_a_only": 0,
            "gap_b_only": 0,
        },
        "obligations": [],
    }
    write_json(out / "mapping.json", mapping)
    write_json(out / "conflicts.json", conflicts)
    write_json(out / "coverage.json", coverage)
    write_json(out / "run.json", {"run_id": out.name, "dry_run": True, "docs": docs, "merges": []})
    return mapping, conflicts, coverage, docs


def run_reconcile(estate_a, estate_b, output, dry_run=False, limit=None):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    run_id = out.name
    print(f"== reconcile {run_id} ==")

    if dry_run:
        print("DRY RUN — no SuperDocs calls, no content-based matching.")
        mapping, conflicts, coverage, docs = dry_run_inventory(estate_a, estate_b, out, limit=limit)
        report.write_review_artifacts(out, run_id, mapping, conflicts, coverage, merges=[], dry_run=True)
        print(f"Wrote {out / 'review.html'} (dry-run banner).")
        return

    client.load_dotenv()
    print("verify API key (GET /v1/sessions)")
    client.verify_key()
    status = client.check_quota_or_stop()
    if status:
        quota = status.get("quota") or {}
        print(f"quota: {quota.get('remaining')}/{quota.get('monthly_limit')} remaining ({status.get('tier')})")

    print("stage 1 ingest")
    docs, compare_session_id = ingest(estate_a, estate_b, run_id, limit=limit)

    print("stage 2 extract")
    obligations, extract_job_ids = extract(docs)
    write_json(out / "obligations.json", {"obligations": obligations})

    print("stage 3–4 match + classify")
    match_payload, match_job_id = match(docs, obligations, compare_session_id)
    mapping = classify(match_payload, docs)

    print("stage 5 detect_conflicts")
    conflicts = detect_conflicts(obligations, match_payload)
    coverage = build_coverage(obligations, match_payload, docs)

    print("stage 6 draft_merges")
    merges = draft_merges(mapping, run_id, out)

    write_json(out / "mapping.json", mapping)
    write_json(out / "conflicts.json", conflicts)
    write_json(out / "coverage.json", coverage)
    run_manifest = {
        "run_id": run_id,
        "compare_session_id": compare_session_id,
        "extract_job_ids": extract_job_ids,
        "match_job_id": match_job_id,
        "docs": docs,
        "merges": merges,
        "mapping": mapping,
    }
    write_json(out / "run.json", run_manifest)

    print("stage 7 report")
    report.write_review_artifacts(out, run_id, mapping, conflicts, coverage, merges=merges, dry_run=False)
    print(f"Done. Open {out / 'review.html'} then edit {out / 'decisions.yaml'}.")
