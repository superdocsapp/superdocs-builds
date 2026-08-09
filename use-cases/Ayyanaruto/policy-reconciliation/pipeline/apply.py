"""Apply decisions.yaml: copy-through, SuperDocs HITL approve/reject, export."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .common import client, slug, write_json


def _copy_through(src, final_dir, prefix):
    src = Path(src)
    dest = Path(final_dir) / f"{prefix}_{src.name}"
    shutil.copy2(src, dest)
    return dest


def apply_decisions(decisions, run_manifest, output_dir):
    """Play back decisions.yaml. One failure must not block the rest."""
    final_dir = Path(output_dir) / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    results = []
    mapping = run_manifest.get("mapping") or {}
    if not mapping.get("policies"):
        mapping_path = Path(output_dir) / "mapping.json"
        if mapping_path.is_file():
            mapping = json.loads(mapping_path.read_text(encoding="utf-8"))

    for policy in mapping.get("policies") or []:
        rec = policy.get("recommendation")
        if rec not in ("keep_a", "keep_b"):
            continue
        doc = policy.get("doc_a") if rec == "keep_a" else policy.get("doc_b")
        try:
            dest = _copy_through(doc["path"], final_dir, prefix=rec)
            results.append({"id": policy["id"], "kind": "policy", "action": rec, "status": "ok", "path": str(dest)})
        except Exception as exc:
            results.append({"id": policy["id"], "kind": "policy", "action": rec, "status": "error", "error": str(exc)})

    docs_by_name = {(d.get("estate"), d.get("filename")): d for d in run_manifest.get("docs") or []}

    for item in decisions.get("conflicts") or []:
        decision = str(item.get("decision") or "pending").lower().strip()
        cid = item.get("id")
        if decision == "pending":
            results.append({"id": cid, "kind": "conflict", "action": "skip", "status": "pending"})
            continue
        try:
            if decision in ("keep_a", "keep_b"):
                estate = "a" if decision == "keep_a" else "b"
                filename = item.get("document_a") if estate == "a" else item.get("document_b")
                doc = docs_by_name.get((estate, filename))
                dest = _copy_through(doc["path"], final_dir, prefix=f"conflict_{decision}")
                results.append({"id": cid, "kind": "conflict", "action": decision, "status": "ok", "path": str(dest)})
            else:
                results.append({"id": cid, "kind": "conflict", "action": decision, "status": "recorded"})
        except Exception as exc:
            results.append({"id": cid, "kind": "conflict", "action": decision, "status": "error", "error": str(exc)})

    merges_by_id = {m["id"]: m for m in run_manifest.get("merges") or []}
    for item in decisions.get("merges") or []:
        decision = str(item.get("decision") or "pending").lower().strip()
        mid = item.get("id")
        if decision == "pending":
            results.append({"id": mid, "kind": "merge", "action": "skip", "status": "pending"})
            continue
        meta = merges_by_id.get(mid)
        try:
            if not meta:
                raise client.SuperDocsError(f"No run.json merge metadata for {mid}")
            if decision == "approve":
                pending = client.parse_pending_changes(meta.get("pending_changes"))
                changes = [
                    {"change_id": c["change_id"], "approved": True}
                    for c in pending
                    if c.get("change_id")
                ]
                client.approve(
                    meta["session_id"],
                    meta["job_id"],
                    True,
                    changes=changes or None,
                )
                job = client.poll_job(meta["job_id"], session_id=meta["session_id"], allow_approval=False)
                if job.get("status") != "completed":
                    raise client.SuperDocsError(f"Merge {mid} status after approve: {job.get('status')}")
                dest = Path(output_dir) / "final" / f"{slug(meta.get('title') or mid)}.docx"
                client.export_docx(
                    dest,
                    session_id=meta["session_id"],
                    filename=slug(meta.get("title") or mid),
                )
                results.append({"id": mid, "kind": "merge", "action": "approve", "status": "ok", "path": str(dest)})
            elif decision == "reject":
                pending = client.parse_pending_changes(meta.get("pending_changes"))
                changes = [
                    {"change_id": c["change_id"], "approved": False}
                    for c in pending
                    if c.get("change_id")
                ]
                client.approve(
                    meta["session_id"],
                    meta["job_id"],
                    False,
                    changes=changes or None,
                    feedback=(item.get("reviewer_notes") or "Rejected by reviewer."),
                )
                results.append({"id": mid, "kind": "merge", "action": "reject", "status": "ok"})
            else:
                results.append({"id": mid, "kind": "merge", "action": decision, "status": "unknown"})
        except Exception as exc:
            results.append({"id": mid, "kind": "merge", "action": decision, "status": "error", "error": str(exc)})

    write_json(Path(output_dir) / "apply_results.json", {"results": results})
    return results


def run_apply(decisions_path):
    import yaml

    decisions_path = Path(decisions_path)
    if not decisions_path.is_file():
        raise client.SuperDocsError(f"decisions file not found: {decisions_path}")
    output_dir = decisions_path.parent
    run_path = output_dir / "run.json"
    if not run_path.is_file():
        raise client.SuperDocsError(f"run.json not found next to decisions: {run_path}")
    client.load_dotenv()
    decisions = yaml.safe_load(decisions_path.read_text(encoding="utf-8")) or {}
    run_manifest = json.loads(run_path.read_text(encoding="utf-8"))
    print(f"== apply {run_manifest.get('run_id') or output_dir.name} ==")
    if run_manifest.get("dry_run"):
        raise client.SuperDocsError("This run was a dry-run. Re-run reconcile without --dry-run before apply.")
    client.verify_key()
    results = apply_decisions(decisions, run_manifest, output_dir)
    ok = sum(1 for r in results if r.get("status") == "ok")
    err = sum(1 for r in results if r.get("status") == "error")
    pending = sum(1 for r in results if r.get("status") == "pending")
    print(f"apply finished: {ok} ok, {err} errors, {pending} still pending")
    for row in results:
        extra = row.get("error") or row.get("path") or ""
        print(f"  {row.get('kind')} {row.get('id')}: {row.get('action')} / {row.get('status')} {extra}")
    return results
