"""Deterministic phrase scoring with source excerpts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from job_architecture.textutil import excerpt, is_negated, split_sentences


@dataclass(frozen=True)
class Hit:
    lexicon: str
    pattern: str
    excerpt: str
    negated: bool
    weight: float
    locator: str = ""


def score_text(
    text: str,
    compiled: tuple[tuple[re.Pattern[str], float, str], ...],
    *,
    lexicon: str,
    locator: str = "",
    honor_negation: bool = True,
) -> tuple[float, tuple[Hit, ...]]:
    if not text.strip():
        return (0.0, ())
    sentences = split_sentences(text)
    hits: list[Hit] = []
    total = 0.0
    seen: set[str] = set()
    for sentence in sentences:
        negated = honor_negation and is_negated(sentence)
        for pattern, weight, raw in compiled:
            if not pattern.search(sentence):
                continue
            key = f"{raw}::{sentence}"
            if key in seen:
                continue
            seen.add(key)
            signed = -weight if negated else weight
            total += signed
            hits.append(
                Hit(
                    lexicon=lexicon,
                    pattern=raw,
                    excerpt=excerpt(sentence),
                    negated=negated,
                    weight=signed,
                    locator=locator,
                )
            )
    return (round(total, 4), tuple(hits))


def format_hit(hit: Hit) -> str:
    polarity = "counter" if hit.negated or hit.weight < 0 else "support"
    locator = hit.locator or hit.lexicon
    return f"[{locator} / {polarity}] {hit.excerpt}"
