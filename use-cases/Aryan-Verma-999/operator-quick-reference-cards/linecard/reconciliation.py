"""Sanitized, bounded reconciliation records for live M1 runs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SECRET_KEYS = {"authorization", "api_key", "upload_url", "curl_example", "cookie"}
RAW_PROVIDER_ID_KEYS = {"chunk_id", "target_chunk_id", "root_chunk_id", "heading_chunk_id", "provider_chunk_ids"}
PRIVATE_ID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.I)

def sanitize(value: Any, _ids: dict[str, str] | None = None) -> Any:
    _ids = {} if _ids is None else _ids
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in SECRET_KEYS | RAW_PROVIDER_ID_KEYS else sanitize(v, _ids) for k, v in value.items()}
    if isinstance(value, list): return [sanitize(v, _ids) for v in value]
    if isinstance(value, str):
        def replacement(match):
            original = match.group(0)
            if original not in _ids:
                _ids[original] = f"00000000-0000-4000-8000-{len(_ids)+1:012d}"
            return _ids[original]
        return PRIVATE_ID.sub(replacement, value)
    return value

def html_sha256(value: str) -> str: return hashlib.sha256(value.encode()).hexdigest()


def chunk_reconciliation(mapping: dict[str, dict[str, Any]], proposals: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a public-safe direct-ID reconciliation summary.

    Raw provider chunk IDs are intentionally kept in memory only. This summary
    is sufficient to prove whether every proposal has an owner without making
    opaque provider identifiers part of a run artifact.
    """
    synchronized = {str(chunk) for item in mapping.values() for chunk in item.get("provider_chunk_ids", ()) if chunk}
    proposed = {str(item.get("chunk_id") or item.get("target_chunk_id")) for item in proposals if item.get("chunk_id") or item.get("target_chunk_id")}
    shared = synchronized & proposed
    return {
        "synchronized_chunk_count": len(synchronized),
        "proposal_chunk_count": len(proposed),
        "chunk_intersection_count": len(shared),
        "all_proposals_owned": bool(proposed) and proposed <= synchronized,
        "synchronized_chunk_id_hashes": sorted(html_sha256(chunk) for chunk in synchronized),
        "proposal_chunk_id_hashes": sorted(html_sha256(chunk) for chunk in proposed),
    }

def bounded_diff(before: str, after: str, limit: int = 1200) -> dict[str, Any]:
    # Block-level comparison avoids persisting complete provider responses.
    def blocks(text: str) -> dict[str, str]:
        return {m.group(1).split()[-1]: hashlib.sha256(m.group(0).encode()).hexdigest() for m in re.finditer(r"<section[^>]*class=\"([^\"]*card-page[^\"]*)\"[^>]*>.*?</section>", text, re.S)}
    a, b = blocks(before), blocks(after)
    return {"before_blocks": a, "after_blocks": b, "changed_blocks": sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k)), "truncated": len(before) + len(after) > limit}

def write_run_artifact(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(sanitize(record), indent=2, ensure_ascii=False) + "\n").encode()
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)
