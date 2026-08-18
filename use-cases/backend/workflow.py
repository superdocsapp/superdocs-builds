import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def apply_local_decisions(checkpoint: dict[str, Any], decisions: dict[str, str]) -> dict[str, Any]:
    """Apply item-level decisions to the document; rejected edits never reach export."""
    original_html = checkpoint.get("original_html", checkpoint.get("updated_html", ""))
    final_html = original_html
    approved_changes = []
    rejected_changes = []

    for change in checkpoint.get("changes", []):
        cid = change.get("change_id")
        decision = decisions.get(cid)
        if decision == "approve":
            old_html = change.get("old_html")
            new_html = change.get("new_html")
            if old_html and new_html and old_html in final_html:
                final_html = final_html.replace(old_html, new_html, 1)
            approved_changes.append(change)
        elif decision == "reject":
            rejected_changes.append(change)

    checkpoint["decisions"] = decisions
    checkpoint["approved_changes"] = approved_changes
    checkpoint["rejected_changes"] = rejected_changes
    checkpoint["updated_html"] = final_html
    checkpoint["workflow_status"] = "approved"
    return checkpoint
