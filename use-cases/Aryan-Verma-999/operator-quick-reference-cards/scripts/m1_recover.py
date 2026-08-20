"""Read-only recovery for one hashed M1 job.

This script never calls the approval or export endpoints. It exists so a run
that lost its SSE stream can still prove (or disprove) direct proposal-to-chunk
ownership from the provider's durable read-back.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parents[1]))

from linecard.reconciliation import chunk_reconciliation, html_sha256, write_run_artifact
from linecard.staging import normalize_document_identities, parse_document_sync, proposal_slot
from linecard.superdocs_client import SuperDocsClient, document_html, normalize_proposals, response_items


ROOT = Path(__file__).parents[1]


def _session_id(item: dict[str, Any]) -> str | None:
    value = item.get("session_id") or item.get("id")
    return str(value) if value else None


def _document_sync_event(job: dict[str, Any]) -> dict[str, Any] | None:
    metadata = job.get("metadata") or {}
    events = metadata.get("intermediate_responses") or job.get("intermediate_responses") or []
    for event in events:
        if not isinstance(event, dict):
            continue
        # Polling may retain the decoded SSE event directly, or preserve it
        # under `data`. Accept only an explicitly typed document_sync event;
        # do not infer a target from arbitrary content.
        candidate = event.get("data", event)
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except json.JSONDecodeError:
                continue
        if isinstance(candidate, dict) and candidate.get("type") == "document_sync":
            return candidate
    return None


def recover(job_sha256: str, *, session_limit: int = 40) -> dict[str, Any]:
    client = SuperDocsClient()
    sessions = response_items(client.sessions(), "sessions")[:session_limit]
    found: tuple[str, dict[str, Any]] | None = None
    for entry in sessions:
        session_id = _session_id(entry)
        if not session_id:
            continue
        for job in response_items(client.session_jobs(session_id), "jobs"):
            job_id = str(job.get("job_id") or job.get("id") or "")
            if job_id and hashlib.sha256(job_id.encode()).hexdigest() == job_sha256:
                found = (session_id, job)
                break
        if found:
            break
    if not found:
        raise RuntimeError("hashed job was not found in the bounded session recovery window")

    session_id, job = found
    job_id = str(job.get("job_id") or job.get("id") or "")
    job = client.job(job_id)
    proposals = normalize_proposals((job.get("metadata") or {}).get("pending_changes", []))
    if not proposals:
        raise RuntimeError("recovered job has no pending proposals")
    target = str(proposals[0].get("document_id") or proposals[0].get("target_document_id") or "")
    if not target or any(str(item.get("document_id") or item.get("target_document_id") or "") != target for item in proposals):
        raise RuntimeError("recovered proposals do not name one explicit staging document")

    roster = response_items(client.session_documents(session_id), "documents")
    forms = normalize_document_identities(roster)
    entry = next((item for item in roster if target in {str(item.get("document_id") or ""), str(item.get("durable_document_id") or "")}), None)
    if not entry:
        raise RuntimeError("recovered proposal target is absent from the session roster")
    durable = str(entry.get("durable_document_id") or entry.get("document_id") or "")
    sync_event = _document_sync_event(job)
    html = document_html(sync_event)
    sync_source = "job_intermediate_document_sync" if html else "durable_document_readback"
    detail = client.detail(durable)
    html = html or document_html(detail)
    if not html:
        raise RuntimeError("durable staging document did not return authoritative HTML")
    mapping = parse_document_sync(html, document_id=durable, version=detail.get("version"))
    document_forms = next((value for value in forms.values() if target in value or durable in value), {target, durable})
    for item in mapping.values():
        item["document_id_forms"] = set(document_forms)

    reconciliation = chunk_reconciliation(mapping, proposals)
    unresolved: list[str] = []
    for proposal in proposals:
        try:
            proposal_slot(proposal, mapping)
        except ValueError as exc:
            unresolved.append(str(exc))
    return {
        "status": "DIRECT_OWNERSHIP_PROVEN" if not unresolved else "BLOCKED_REAL_DEFECT",
        "read_only": True,
        "approval_attempted": False,
        "export_attempted": False,
        "job_state": job.get("status"),
        "sync_source": sync_source,
        "pending_proposal_count": len(proposals),
        "staging_html_sha256": html_sha256(html),
        "document_id_forms_sha256": hashlib.sha256("|".join(sorted(document_forms)).encode()).hexdigest(),
        "reconciliation": reconciliation,
        "unresolved_change_count": len(unresolved),
        "unresolved_reasons": sorted(set(unresolved)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-sha256", required=True)
    parser.add_argument("--session-limit", type=int, default=40)
    args = parser.parse_args()
    try:
        result = recover(args.job_sha256, session_limit=args.session_limit)
    except (RuntimeError, ValueError) as exc:
        result = {
            "status": "BLOCKED_REAL_DEFECT",
            "read_only": True,
            "approval_attempted": False,
            "export_attempted": False,
            "recovery_error": str(exc),
        }
    write_run_artifact(result, ROOT / "artifacts" / "m1" / "recovery-sanitized.json")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "DIRECT_OWNERSHIP_PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
