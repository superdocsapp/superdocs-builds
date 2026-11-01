from __future__ import annotations

import json
from typing import Any


def maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s or not (s.startswith("{") or s.startswith("[")):
        return value
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return value


def pending_changes(job: dict) -> list[dict]:
    meta = job.get("metadata") or {}
    raw = meta.get("pending_changes") or []
    out = []
    for item in raw:
        if isinstance(item, str):
            item = maybe_json(item)
        if isinstance(item, dict):
            out.append(item)
    events = meta.get("intermediate_responses") or []
    if not out:
        for ev in events:
            content = maybe_json((ev or {}).get("content"))
            if isinstance(content, dict) and content.get("changes"):
                out.extend(content["changes"])
            elif isinstance(content, list):
                out.extend(content)
    return out


def awaiting_kind(job: dict) -> str | None:
    meta = job.get("metadata") or {}
    kind = meta.get("awaiting_kind")
    if kind:
        return str(kind)
    if meta.get("continue_prompt"):
        return "continue_prompt"
    if pending_changes(job):
        return "hitl"
    return None


def is_continue_prompt(job: dict) -> bool:
    return awaiting_kind(job) == "continue_prompt"


def encode_approve_all(job_id: str, changes: list[dict], *, index_document_id: str | None) -> dict:
    """Batch body with required top-level approved. Deny evidence-tab edits."""
    entries = []
    for ch in changes:
        cid = ch.get("change_id")
        if not cid:
            continue
        doc = ch.get("document_id")
        approved = True
        if index_document_id and doc and doc != index_document_id:
            approved = False
        entries.append({"change_id": cid, "approved": approved})
    return {"job_id": job_id, "approved": True, "changes": entries}


def encode_approve_one(job_id: str, change_id: str, approved: bool, feedback: str | None = None) -> dict:
    body: dict[str, Any] = {"job_id": job_id, "change_id": change_id, "approved": approved}
    if feedback:
        body["feedback"] = feedback
    return body


def encode_continue(job_id: str, resume: bool = True) -> dict:
    return {"job_id": job_id, "continue": resume}


def usage_ops(job: dict) -> int:
    result = job.get("result") or {}
    usage = result.get("usage") or job.get("usage") or {}
    ops = usage.get("ops_charged")
    return int(ops) if ops is not None else 0
