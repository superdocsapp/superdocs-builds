"""Deterministic local retrieval, FTS5 indexing, and fail-closed hint mapping."""
from __future__ import annotations
import re, sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

STOP = {"the", "and", "for", "with", "from", "this", "that", "into", "clear"}

@dataclass(frozen=True)
class EvidenceHit:
    page_index: int; quote: str; reasons: tuple[str, ...]; score: float

def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9][a-z0-9-]+", value.lower()) if x not in STOP}

class EvidenceIndex:
    def __init__(self, connection: sqlite3.Connection | None = None):
        self.db = connection or sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE IF NOT EXISTS pages(page_index INTEGER PRIMARY KEY, printed_label TEXT, text TEXT NOT NULL)")
        self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS page_fts USING fts5(text, content='pages', content_rowid='page_index')")
        self.db.commit()

    def add_manifest(self, manifest: dict[str, Any]) -> None:
        for page in manifest["pages"]:
            self.db.execute("INSERT OR REPLACE INTO pages(page_index, printed_label, text) VALUES(?,?,?)", (page["pdf_index"], page.get("printed_page_label"), page["text"]))
        self.db.execute("INSERT INTO page_fts(page_fts) VALUES('rebuild')"); self.db.commit()

    def search(self, query: str, limit: int = 20) -> list[EvidenceHit]:
        terms = _tokens(query); hits: list[EvidenceHit] = []
        for row in self.db.execute("SELECT page_index,text FROM pages"):
            page, text = row; low = text.lower(); matched = {t for t in terms if t in low}
            if not matched: continue
            reasons = ["phrase_search"] if query.lower() in low else ["token_search"]
            score = len(matched) / max(1, len(terms))
            hits.append(EvidenceHit(page, text[:800], tuple(reasons), score))
        return sorted(hits, key=lambda h: (-h.score, h.page_index))[:limit]

    def safety_sweep(self) -> list[EvidenceHit]:
        return self.search("warning isolate energy lockout interlock PPE", 100)

    def specification_sweep(self) -> list[EvidenceHit]:
        pattern = re.compile(r"\b\d+(?:\.\d+)?\s*(?:N·m|Nm|psi|bar|°C|mm|s|rpm)\b|±")
        return [EvidenceHit(p, pattern.search(t).group(0), ("specification_sweep",), 1.0) for p,t in self.db.execute("SELECT page_index,text FROM pages") if pattern.search(t)]

def map_semantic_hint(hint: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Map a semantic hint to one exact page/span, otherwise reject it."""
    quote = str(hint.get("quote") or hint.get("text") or "").strip()
    candidates = []
    for page in manifest["pages"]:
        start = page["text"].find(quote) if quote else -1
        if start >= 0: candidates.append((page, start))
    if len(candidates) != 1:
        raise ValueError("semantic hint is unmapped or ambiguous")
    page, start = candidates[0]
    return {"page_index": page["pdf_index"], "quote": quote, "start": start, "end": start + len(quote), "channel": "superdocs-semantic"}
