"""Item-level review: approved sections fill, rejected sections stay template."""

from __future__ import annotations


def preview_html(baseline: str, queue: list[dict], decisions: dict[str, bool]) -> str:
    html = (baseline or "").replace("\r\n", "\n")
    for item in queue:
        if decisions.get(item["change_id"]) is not True:
            continue
        old = (item.get("old_html") or "").replace("\r\n", "\n")
        new = (item.get("new_html") or "").replace("\r\n", "\n")
        if old and old in html:
            html = html.replace(old, new, 1)
    return html


def record_decision(rec: dict, incoming: dict[str, bool]) -> None:
    rec.setdefault("decisions", {}).update(incoming)
    queue = rec.get("queue") or rec.get("changes") or []
    rec["queue"] = queue
    rec["html"] = preview_html(rec["baseline_html"], queue, rec["decisions"])
    rec["changes"] = [c for c in queue if c["change_id"] not in rec["decisions"]]
    rec["register"] = [
        {
            "change_id": c["change_id"],
            "label": c.get("ai_explanation") or c["change_id"],
            "decision": rec["decisions"].get(c["change_id"]),
        }
        for c in queue
    ]
    if rec["changes"]:
        rec["status"] = "awaiting_approval"
        rec["applied"] = None
    else:
        rec["status"] = "completed"
        rec["applied"] = any(rec["decisions"].values())


def items_to_queue(items: list[dict]) -> dict:
    return {
        "mode": "offline",
        "status": "awaiting_approval",
        "html": "",
        "changes": items,
        "queue": items,
        "decisions": {},
        "register": [
            {"change_id": c["change_id"], "label": c.get("ai_explanation") or c["change_id"], "decision": None}
            for c in items
        ],
        "applied": None,
    }
