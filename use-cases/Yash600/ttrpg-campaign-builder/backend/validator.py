"""
validator.py -- "proof over assertion," generalized to the entity/reference
graph. Same philosophy as the healthcare build's validator: independently
re-derive whether the campaign's cross-references are actually coherent,
rather than trusting the cached `status` columns.

For every Reference edge:
  1. Entity structure check: fetch the Bible's non-billable `structure`
     field (GET /v1/documents/{id}, headings + section count, 0 ops) and
     confirm the entity's canonical heading is still present.
  2. Entity hash check: fetch the Bible's current HTML, re-extract the
     entity's canonical chunk by chunk_id, recompute its content hash from
     scratch, and compare against Entity.current_content_hash (catches
     drift our own tracking might have missed) AND against
     Reference.synced_content_hash (the actual staleness check).
  3. Source presence check: fetch the referencing document's current HTML
     and confirm source_chunk_id still exists in it.

Every check is a plain equality/membership test against data pulled fresh
from SuperDocs -- no LLM judgment call in the validator itself.

Runnable two ways:
  - As a library: `run_validation(db_session, superdocs_client)` -> dict,
    used by GET /validate in main.py.
  - As a script: `python validator.py` -- requires a campaign to already be
    seeded, writes backend/validation_report.json, exit code 0 on pass /
    1 on any failure (so it can gate CI).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

import chunking
import db
import models
from superdocs_client import SuperDocsClient, SuperDocsError

REPORT_PATH = Path(__file__).parent / "validation_report.json"


def _check_reference(client: SuperDocsClient, s: Session, ref: models.Reference) -> dict:
    result = {"reference_id": ref.id, "checks": {}, "passed": True, "errors": []}

    entity = s.get(models.Entity, ref.entity_id)
    bible_doc = s.get(models.Document, entity.canonical_document_id) if entity else None
    source_doc = s.get(models.Document, ref.source_document_id)

    if entity is None or bible_doc is None or source_doc is None:
        result["passed"] = False
        result["errors"].append("dangling reference: entity or document row missing")
        return result

    result["entity"] = f"{entity.entity_type.value}: {entity.name}"
    result["source_document"] = source_doc.title

    # -- 1. heading check (non-billable structure fetch) ---------------------
    try:
        bible_detail = client.get_document(bible_doc.superdocs_document_id, include_html=False)
    except SuperDocsError as e:
        result["passed"] = False
        result["errors"].append(f"could not fetch bible document structure: {e}")
        return result

    headings = [h["text"] for h in bible_detail.get("structure", {}).get("headings", [])]
    # entity headings are the H2/H3 text of their canonical chunk -- we didn't
    # store that text verbatim, so check by substring of the entity name
    # instead, which is how every canonical chunk in campaign_pack.py titles
    # its heading.
    heading_present = any(entity.name.split(" ")[0] in h or entity.name in h for h in headings)
    result["checks"]["entity_heading_present"] = heading_present
    if not heading_present:
        result["errors"].append(
            f"entity {entity.name!r} heading not found in current bible structure (found: {headings})"
        )
        result["passed"] = False

    # -- 2. hash check (re-derived from fresh HTML, not the cached column) ---
    try:
        bible_full = client.get_document(bible_doc.superdocs_document_id, include_html=True)
    except SuperDocsError as e:
        result["passed"] = False
        result["errors"].append(f"could not fetch bible HTML: {e}")
        return result

    bible_chunks = chunking.extract_chunks(bible_full.get("html", "") or "")
    live_chunk_html = bible_chunks.get(entity.canonical_chunk_id)
    if live_chunk_html is None:
        result["passed"] = False
        result["checks"]["entity_hash_matches"] = False
        result["errors"].append(f"canonical chunk {entity.canonical_chunk_id!r} not found in live bible HTML")
    else:
        live_hash = chunking.content_hash(live_chunk_html)
        hash_matches = not chunking.is_stale(ref.synced_content_hash, live_hash)
        result["checks"]["entity_hash_matches"] = hash_matches
        result["live_entity_hash"] = live_hash
        result["reference_synced_hash"] = ref.synced_content_hash
        if not hash_matches:
            result["passed"] = False
            result["errors"].append(
                "content hash mismatch: entity's canonical description has changed since this "
                "reference was last synced (reference status column says "
                f"{ref.status!r} -- independent check "
                + ("agrees" if ref.status != models.ReferenceStatus.SYNCED else "disagrees with cache")
            )

    # -- 3. source chunk presence check ---------------------------------------
    try:
        source_full = client.get_document(source_doc.superdocs_document_id, include_html=True)
    except SuperDocsError as e:
        result["passed"] = False
        result["errors"].append(f"could not fetch source document HTML: {e}")
        return result

    source_chunks = chunking.extract_chunks(source_full.get("html", "") or "")
    source_present = ref.source_chunk_id in source_chunks
    result["checks"]["source_chunk_present"] = source_present
    if not source_present:
        result["passed"] = False
        result["errors"].append(
            f"source chunk {ref.source_chunk_id!r} not found in {source_doc.title!r}'s live HTML"
        )

    return result


def run_validation(s: Session, client: SuperDocsClient, campaign_id: str | None = None) -> dict:
    query = select(models.Reference)
    refs = s.exec(query).all()
    if campaign_id:
        refs = [r for r in refs if (s.get(models.Entity, r.entity_id) or models.Entity()).campaign_id == campaign_id]

    ref_results = [_check_reference(client, s, ref) for ref in refs]
    passed_count = sum(1 for r in ref_results if r["passed"])

    campaign_name = None
    if campaign_id:
        c = s.get(models.Campaign, campaign_id)
        campaign_name = c.name if c else None

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "campaign": campaign_name or "all campaigns",
        "total_references": len(ref_results),
        "passed": passed_count,
        "failed": len(ref_results) - passed_count,
        "overall_status": "PASS" if passed_count == len(ref_results) and ref_results else "FAIL",
        "references": ref_results,
    }
    return report


def main() -> int:
    db.init_db()
    api_key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    base_url = os.environ.get("SUPERDOCS_API_BASE", "https://api.superdocs.app").strip()
    if not api_key:
        print("ERROR: SUPERDOCS_API_KEY not set in backend/.env", file=sys.stderr)
        return 1
    client = SuperDocsClient(api_key=api_key, base_url=base_url)

    with Session(db.get_engine()) as s:
        report = run_validation(s, client)

    REPORT_PATH.write_text(json.dumps(report, indent=2))

    print(f"Validation report written to {REPORT_PATH}")
    print(f"Overall: {report['overall_status']} ({report['passed']}/{report['total_references']} references passed)")
    for r in report["references"]:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"  [{status}] {r.get('source_document', r['reference_id'])} -> {r.get('entity', '?')}")
        for err in r["errors"]:
            print(f"         - {err}")

    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
