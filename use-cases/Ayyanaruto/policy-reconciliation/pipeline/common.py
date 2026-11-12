"""Shared helpers used by every stage."""

from __future__ import annotations

import json
import re
from pathlib import Path

import superdocs_client as client

RECOMMENDATIONS = {"keep_a", "keep_b", "merge", "new"}
DISPOSITIONS = {"mapped", "gap-A-only", "gap-B-only"}


def slug(text, limit=40):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(text)).strip("_").lower()
    return (s or "doc")[:limit]


def list_docx(folder, limit=None):
    paths = sorted(Path(folder).glob("*.docx"))
    if limit is not None:
        paths = paths[: int(limit)]
    if not paths:
        raise client.SuperDocsError(f"No .docx files found in {folder}")
    return paths


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def chat_json(prompt, session_id, *, document_id=None, model_tier="core"):
    """chat_async + parse JSON. Returns (payload_or_None, job)."""
    job = client.chat_async(
        prompt,
        session_id,
        document_id=document_id,
        model_tier=model_tier,
    )
    return client.parse_json_from_reply(client.reply_text(job)), job


def esc(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
