"""SuperDocs four-call contract: upload, chat, approve, export.

Proposed-change content from SuperDocs can be a JSON *string* and needs a
second parse (their integrator note). Tests cover that without a live key.
"""

from __future__ import annotations

import json
from typing import Any


def parse_proposed_change_content(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def parse_change_batch(payload: dict) -> list[dict]:
    batch = payload.get("changes") or payload.get("pending_changes") or []
    out = []
    for item in batch:
        item = dict(item)
        if "content" in item:
            item["content"] = parse_proposed_change_content(item["content"])
        if "html" in item and isinstance(item["html"], str) and item["html"].startswith("{"):
            item["html"] = parse_proposed_change_content(item["html"])
        out.append(item)
    return out


class FakeDocs:
    """Stand-in for upload → chat → approve → export."""

    def __init__(self) -> None:
        self.docs: dict[str, str] = {}
        self.pending: dict[str, list[dict]] = {}
        self.exports: list[str] = []
        self.ops = 0
        self.sample_mode = True

    def upload(self, doc_id: str, html_or_md: str) -> dict:
        self.docs[doc_id] = html_or_md
        return {"document_id": doc_id}

    def chat(self, doc_id: str, instruction: str) -> dict:
        self.ops += 1
        if self.sample_mode and self.ops > 3:
            return {"status": "stopped", "reason": "small-sample mode (stopping rule)"}
        change = {
            "change_id": f"ch_{self.ops}",
            "content": json.dumps({"instruction": instruction, "doc_id": doc_id}),
        }
        self.pending.setdefault(doc_id, []).append(change)
        return {"status": "awaiting_approval", "changes": [change]}

    def approve(self, doc_id: str, change_id: str, approved: bool) -> dict:
        kept = []
        applied = []
        for ch in self.pending.get(doc_id, []):
            if ch["change_id"] == change_id:
                if approved:
                    parsed = parse_proposed_change_content(ch["content"])
                    extra = parsed.get("instruction", "") if isinstance(parsed, dict) else str(parsed)
                    self.docs[doc_id] = self.docs.get(doc_id, "") + "\n" + extra
                    applied.append(change_id)
                continue
            kept.append(ch)
        self.pending[doc_id] = kept
        return {"applied": applied, "remaining": [c["change_id"] for c in kept]}

    def export(self, doc_id: str, fmt: str = "docx") -> dict:
        self.exports.append(doc_id)
        return {"format": fmt, "bytes": self.docs.get(doc_id, "").encode("utf-8")}
