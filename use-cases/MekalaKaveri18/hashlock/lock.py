"""Byte-identity locks for SuperDocs edits.

Mark a region with data-lock="true" and an id. After SuperDocs (or an offline
edit) returns HTML, those inner bytes must hash the same. Unlocked regions are
allowed to change. A FAIL is a successful demonstration of the tool.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / "fixtures" / "msa-excerpt.html").read_text(encoding="utf-8")

LOCK_RE = re.compile(
    r"<(?P<tag>\w+)(?P<attrs>[^>]*\bdata-lock=(['\"])true\3[^>]*)>(?P<body>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)
ID_RE = re.compile(r'\bid=(["\'])(?P<id>[^"\']+)\1', re.IGNORECASE)


def locked_bodies(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in LOCK_RE.finditer(html):
        ident = ID_RE.search(m.group("attrs") or "")
        key = ident.group("id") if ident else f"anon-{len(out)}"
        out[key] = m.group("body")
    return out


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprints(html: str) -> dict[str, str]:
    return {k: sha256(v) for k, v in locked_bodies(html).items()}


def proof(before_html: str, after_html: str) -> dict:
    before = fingerprints(before_html)
    after = fingerprints(after_html)
    rows = []
    held = True
    for key, digest in before.items():
        match = after.get(key) == digest
        if not match:
            held = False
        rows.append({"id": key, "before": digest, "after": after.get(key), "held": match})
    unlocked_changed = before_html != after_html
    return {
        "locks": rows,
        "all_locks_held": held,
        "document_changed": unlocked_changed,
        "verdict": "PASS" if held and unlocked_changed else ("FAIL" if not held else "NO-OP"),
    }


def instruction() -> str:
    return (
        "This HTML has sections marked data-lock=\"true\". Do not change the inner HTML "
        "of any locked section (parties, governing-law, limitation-of-liability). "
        "Tighten only the unlocked service-description paragraph: make it specific to "
        "a 90-day vendor-analyst pilot, keep it under 80 words, do not invent fees."
    )


def offline_tighten(html: str) -> str:
    """Change only the unlocked service paragraph. Locks stay byte-identical."""
    return re.sub(
        r'(id="service-description"[^>]*>)(.*?)(</p>)',
        r"\1Pilot scope: ingest a vendor pile, classify documents, extract fields, "
        r"reconcile conflicts, and stop at a human gate before any register commit. "
        r"Ninety days. No OCR claim. No live-web browse.\3",
        html,
        count=1,
        flags=re.DOTALL,
    )


def tamper_locked(html: str) -> str:
    """Deliberate lock break — the receipt must FAIL."""
    return html.replace("Acme Vendor Co.", "Totally Different LLC", 1)
