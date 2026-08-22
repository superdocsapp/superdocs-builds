"""
Classifies each `data-chunk-id` element in SuperDocs' parsed HTML as PROTECTED (must survive
byte-identical) or PROSE (safe to adapt). Deliberately rule-based, not an LLM call: getting this
classification wrong is exactly the failure mode this whole build exists to prevent, so it needs to be
inspectable and deterministic, not another place an AI call can quietly drift.

Rule of thumb, stated explicitly because it's a real design choice: WHEN UNCERTAIN, PROTECT. A
false-positive "protected" chunk just means one extra paragraph doesn't get simplified — mildly annoying.
A false-negative (a real equation misclassified as prose and rewritten) silently corrupts course content.
The asymmetry drives every threshold below.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from bs4 import BeautifulSoup, Tag

ChunkKind = Literal["protected", "prose"]

_EQUATION_MARKERS = re.compile(r"\bEquation\s+\d", re.IGNORECASE)
_FIGURE_MARKERS = re.compile(r"\bFigure\s+\d", re.IGNORECASE)
_MATH_HEAVY = re.compile(r"[=×÷±∑∫√πθΔδ]|\b\d+\s*[/÷]\s*\d+\b")
_CAPTION_ITALIC_SHORT = 240  # chars — short italic paragraphs are very likely captions, not body prose


@dataclass
class Chunk:
    chunk_id: str
    tag: str
    text: str
    html: str
    kind: ChunkKind
    reason: str
    content_hash: str


def _hash(html: str) -> str:
    # Whitespace-normalized AND with the data-chunk-id attribute stripped before hashing. The id itself is
    # metadata, not content -- real-world testing (2026-08-22) showed SuperDocs reassigns ids on every
    # turn even for byte-identical content, so including the id value in the hash made every single
    # protected chunk register as "changed" purely because its id moved, never because its actual content
    # did. Stripping it is what makes this a true content hash.
    normalized = re.sub(r'\s*data-chunk-id="[^"]*"', "", html)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def classify_chunk(tag: Tag) -> tuple[ChunkKind, str]:
    tag_name = tag.name
    text = tag.get_text(" ", strip=True)

    if tag_name == "table" or tag.find("table") is not None:
        return "protected", "table (worked-example / data table)"

    if _EQUATION_MARKERS.search(text):
        return "protected", "explicit equation label"

    if _FIGURE_MARKERS.search(text):
        return "protected", "explicit figure label"

    is_italic = tag.find("em") is not None or tag.find("i") is not None
    has_explicit_caption_word = bool(re.search(r"\b(figure|table|diagram|chart|photo|image)\b", text, re.IGNORECASE))
    if is_italic and len(text) <= _CAPTION_ITALIC_SHORT and has_explicit_caption_word:
        return "protected", "short italic text naming a figure/table/diagram, likely a caption"

    if tag.find("img") is not None:
        return "protected", "contains an embedded image"

    math_hits = len(_MATH_HEAVY.findall(text))
    word_count = max(1, len(text.split()))
    if math_hits and (math_hits / word_count) > 0.15:
        return "protected", "high density of mathematical symbols relative to word count"

    if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return "prose", "heading — adaptable prose"

    return "prose", "ordinary paragraph text"


def classify_document(html: str) -> list[Chunk]:
    soup = BeautifulSoup(html, "html.parser")
    chunks: list[Chunk] = []
    for tag in soup.find_all(attrs={"data-chunk-id": True}):
        chunk_id = tag.get("data-chunk-id")
        kind, reason = classify_chunk(tag)
        chunk_html = str(tag)
        chunks.append(Chunk(
            chunk_id=chunk_id, tag=tag.name, text=tag.get_text(" ", strip=True),
            html=chunk_html, kind=kind, reason=reason, content_hash=_hash(chunk_html),
        ))
    return chunks


def protected_ids(html: str) -> list[str]:
    return [c.chunk_id for c in classify_document(html) if c.kind == "protected"]


def prose_ids(html: str) -> list[str]:
    return [c.chunk_id for c in classify_document(html) if c.kind == "prose"]
