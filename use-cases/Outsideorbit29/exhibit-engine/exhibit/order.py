"""Exhibit order: sequencing the evidence pile to follow the brief's argument.

The paralegal's brief makes an argument; the evidence should be presented in the
order the argument relies on it. ``propose_order`` scores every piece of evidence
by how early the sentence in the brief that relies on it appears, and returns the
pile ordered by that. Evidence no brief sentence touches goes last, unchanged
relative to each other, so nothing is silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .citations import (
    _evidence_content_keywords,
    _score_sentence,
    _sentences,
    _topic_keywords,
)


@dataclass
class EvidenceItem:
    """One piece of evidence from the pile: its source file and extracted text."""

    source: str
    text: str


def propose_order(brief: str, items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Order ``items`` so that evidence appears in the order the brief relies on it.

    Each item is anchored at the sentence the brief *most* relies on it for
    (highest weighted topic overlap, earliest when tied) and ordered by that
    sentence's position. Weighting means an exhibit's filename topic (passport,
    lease, bank, ...) dominates body-text noise, and proper nouns never drive
    ordering. Evidence no brief sentence touches goes last, keeping its input
    order, so nothing is silently dropped.
    """
    sentences = _sentences(brief)
    scored: list[tuple[float, int, EvidenceItem]] = []
    for rank, item in enumerate(items):
        title_kw = _topic_keywords(_title_from_source(item.source))
        content_kw = _evidence_content_keywords(item.text)
        if not sentences:
            scored.append((float(rank), rank, item))
            continue
        best: tuple[int, int] | None = None  # (score, offset)
        for start, _end, sent in sentences:
            score, offset = _score_sentence(title_kw, content_kw, start, sent)
            if score and (best is None or (score, -offset) > (best[0], -best[1])):
                best = (score, offset)
        if best is None:
            # No brief sentence relies on this evidence: it goes last, keeping
            # its input order relative to the other unmatched items.
            scored.append((10**9 + rank, rank, item))
        else:
            scored.append((best[1], rank, item))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [item for _score, _rank, item in scored]


def _title_from_source(source: str) -> str:
    base = re.sub(r"^.*[\\/]", "", source)  # basename, so dirs never pollute the title
    base = re.sub(r"\.(pdf|docx?|md|txt|html?|rtf)$", "", base, flags=re.I)
    base = re.sub(r"[-_]+", " ", base)
    return base.strip()
