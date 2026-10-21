"""Small text helpers for deterministic evidence extraction and scoring."""

from __future__ import annotations

import re

UNSTATED = "Not stated in the source job description."

_BULLET_RE = re.compile(r"^(?:[-*•]\s+|\d+\.\s+)(.+)$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")

NEGATION_RE = re.compile(
    r"\b("
    r"do not|does not|don't|doesn't|cannot|can not|"
    r"is not|are not|was not|were not|"
    r"not specified|none stated|not stated|"
    r"there are no|this role does not|does not include|"
    r"you do not|you cannot|without"
    r")\b",
    re.IGNORECASE,
)

SPARSE_MARKERS = (
    re.compile(r"\bas needed\b", re.IGNORECASE),
    re.compile(r"\bas assigned\b", re.IGNORECASE),
    re.compile(r"\bother duties\b", re.IGNORECASE),
    re.compile(r"\bvaries\b", re.IGNORECASE),
    re.compile(r"\bdepends on\b", re.IGNORECASE),
    re.compile(r"\bnot specified\b", re.IGNORECASE),
    re.compile(r"\bnone stated\b", re.IGNORECASE),
    re.compile(r"\bto be determined\b", re.IGNORECASE),
    re.compile(r"\bvarious programs\b", re.IGNORECASE),
    re.compile(r"\bspecial programs\b", re.IGNORECASE),
    re.compile(r"\bhelp with\b", re.IGNORECASE),
    re.compile(r"\bprovide support\b", re.IGNORECASE),
    re.compile(r"\bassist with\b", re.IGNORECASE),
)


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def parse_bullets(text: str) -> list[str]:
    items: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _BULLET_RE.match(line)
        if match:
            item = normalize_whitespace(match.group(1))
            if item:
                items.append(item)
    if items:
        return items
    paragraph = normalize_whitespace(text)
    return [paragraph] if paragraph else []


def split_sentences(text: str) -> list[str]:
    parts = [normalize_whitespace(part) for part in _SENTENCE_SPLIT_RE.split(text)]
    return [part for part in parts if part]


def is_negated(sentence: str) -> bool:
    return bool(NEGATION_RE.search(sentence))


def count_sparse_markers(text: str) -> int:
    return sum(1 for pattern in SPARSE_MARKERS if pattern.search(text))


def excerpt(text: str, limit: int = 220) -> str:
    compact = normalize_whitespace(text)
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def contains_excerpt(source: str, snippet: str) -> bool:
    if not snippet:
        return False

    def blob(text: str) -> str:
        stripped = re.sub(r"[-*•]", " ", text)
        return normalize_whitespace(stripped).lower().replace("…", "")

    needle = blob(snippet)
    haystack = blob(source)
    if needle in haystack:
        return True
    tokens = [part.strip() for part in re.split(r"[./]", snippet) if len(part.strip()) > 24]
    return bool(tokens) and all(blob(part) in haystack for part in tokens)


def first_matching_sentence(sentences: list[str], cues: tuple[re.Pattern[str], ...]) -> list[str]:
    matched: list[str] = []
    for sentence in sentences:
        if any(cue.search(sentence) for cue in cues):
            matched.append(sentence)
    return matched
