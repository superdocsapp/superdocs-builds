"""
design_links.py — tracks which Canva design maps to which SuperDocs
session, the content hash from the last sync, AND a full text
snapshot (needed to compute a real diff on the NEXT sync).

Bug fixed here: the original version only saved a snapshot in the
"change detected" branch, never in the initial registration branch -
so the first real diff after registration always compared against an
empty string instead of the actual original text. update_link now
always takes the snapshot as a required argument, so there's no path
that can skip saving it.
"""
import json
from pathlib import Path

REGISTRY_PATH = Path("design_links.json")


def load_registry() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {}


def save_registry(registry: dict) -> None:
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def get_link(design_id: str) -> dict | None:
    return load_registry().get(design_id)


def update_link(design_id: str, session_id: str, content_hash: str, text_snapshot: str, timestamp: str) -> None:
    registry = load_registry()
    registry[design_id] = {
        "session_id": session_id,
        "last_content_hash": content_hash,
        "last_text_snapshot": text_snapshot,
        "last_synced_at": timestamp,
    }
    save_registry(registry)