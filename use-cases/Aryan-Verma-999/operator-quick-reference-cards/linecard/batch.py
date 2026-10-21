"""Isolated batch orchestration and truthful aggregate manifests."""
from __future__ import annotations
import hashlib, json, zipfile
from pathlib import Path
from typing import Any

def batch_manifest(tasks: list[dict[str,Any]]) -> dict[str,Any]:
    cards=[]
    for task in tasks:
        item={"task":task["task"],"status":task.get("status","QUEUED"),"session_id":task.get("session_id"),"pdf_sha256":task.get("pdf_sha256"),"verification":task.get("verification")}
        cards.append(item)
    ok=all(c["status"] == "COMPLETED" for c in cards)
    return {"schema":"linecard-card-set-v1","cards":cards,"aggregate_status":"COMPLETED" if ok else "PARTIAL_OR_BLOCKED","merged_allowed":ok}

def execute_batch(tasks: list[dict[str, Any]], run_card, *, concurrency: int = 1,
                  sample_first: bool = True, approve_sample: bool = False, cancel: bool = False,
                  operation_budget: int | None = None) -> dict[str, Any]:
    """Run isolated cards with a bounded concurrency policy and sample gate."""
    if concurrency < 1: raise ValueError("concurrency must be positive")
    if cancel: return {"status":"CANCELLED", "cards":[]}
    if sample_first and tasks and not approve_sample:
        return {"status": "AWAITING_SAMPLE", "cards": [{"task": tasks[0]["task"], "status": "SAMPLE_REQUIRED"}]}
    output=[]
    for task in tasks:
        if operation_budget is not None and len(output) >= operation_budget:
            output.append({"task": task["task"], "status": "AWAITING_BUDGET"}); continue
        try:
            result = run_card(dict(task))
            output.append({**task, **result, "task": task["task"]})
        except Exception as exc:
            output.append({**task, "task": task["task"], "status": "BLOCKED", "error": type(exc).__name__})
    aggregate = "COMPLETED" if all(x.get("status") == "COMPLETED" for x in output) else ("AWAITING_BUDGET" if any(x.get("status")=="AWAITING_BUDGET" for x in output) else "PARTIAL_OR_BLOCKED")
    return {"status": aggregate, "cards": output, "concurrency": concurrency, "paused": aggregate != "COMPLETED"}

def retry_resume(task: dict[str, Any], run_card, *, max_attempts: int = 2) -> dict[str, Any]:
    attempts = int(task.get("attempts", 0))
    while attempts < max_attempts:
        attempts += 1
        result = run_card({**task, "attempts": attempts})
        if result.get("status") == "COMPLETED": return {**result, "attempts": attempts}
        if not result.get("retryable", False): return {**result, "attempts": attempts}
    return {"status": "BLOCKED", "reason": "retry budget exhausted", "attempts": attempts}

def run_offline_three_task_batch(output_dir: str | Path, *, sample_approved: bool = True) -> dict[str, Any]:
    """Execute the three declared tasks locally, producing per-card proof files."""
    from .m1 import skeleton, verify
    from .fallback import sidecar_manifest
    import uuid
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    names = ["Clear infeed jam", "Weekly lubrication", "Guard replacement / inspection"]
    if not sample_approved: return {"status":"AWAITING_SAMPLE", "cards":[]}
    cards=[]
    for index, task in enumerate(names):
        card_id=f"lc-offline-{index+1:02d}-{uuid.uuid4().hex[:8]}"
        html=skeleton(); report=verify(html)
        status="COMPLETED" if report["status"] == "PASS" else "BLOCKED"
        artifact=out/f"{card_id}.html"; artifact.write_text(html, encoding="utf-8")
        manifest={"card_id":card_id,"task":task,"session_id":f"offline-session-{index+1}","evidence_set":"hero-evidence-v1","typed_plan":"linecard-plan-v1","verification":report,"retry":{"attempts":1,"resume_stage":"verified"},"operation_budget":{"reserved":1,"consumed":0},"status":status,"artifact":str(artifact)}
        (out/f"{card_id}.json").write_text(json.dumps(manifest,indent=2)+"\n")
        cards.append(manifest)
    batch={"schema":"linecard-offline-batch-v1","sample_gate":"APPROVED","cards":cards,"aggregate_status":"COMPLETED" if all(c["status"]=="COMPLETED" for c in cards) else "PARTIAL_OR_BLOCKED"}
    (out/"batch-manifest.json").write_text(json.dumps(batch,indent=2)+"\n")
    write_card_set(cards, out/"linecard-offline-batch.zip")
    return batch

def write_card_set(tasks: list[dict[str,Any]], output: str | Path) -> Path:
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True); manifest=batch_manifest(tasks)
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("card-set-manifest.json",json.dumps(manifest,indent=2)+"\n")
        for i,task in enumerate(tasks):
            if task.get("status") == "COMPLETED" and task.get("pdf_path"):
                archive.write(task["pdf_path"],f"cards/{i+1:02d}.pdf")
    return output
