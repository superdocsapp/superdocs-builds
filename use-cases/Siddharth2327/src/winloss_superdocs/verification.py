"""Grounding verification.

Two independent checks, both deterministic (no LLM involved):

1. `verify_evidence_quotes` -- every <blockquote data-evidence="true"> in a debrief
   must fuzzy-match a substring of the source transcript. This is the direct
   implementation of "evidence can be traced back to the relevant content" /
   "unsupported claims are not fabricated." Unmatched quotes are NOT silently
   dropped -- they are returned so the caller can label them, per architecture.md §4.

2. `verify_synthesis_numbers` -- every number in the brief's "Patterns by Competitor"
   / "Patterns by Segment" tables must match the index's own ground-truth counts
   exactly. Catches the AI silently "correcting" or mis-copying a count.

Matching is a documented heuristic (normalized substring containment with a
Levenshtein-ratio fallback for near-verbatim quotes), not a semantic guarantee --
see architecture.md §12 "Known limitations."
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from bs4 import BeautifulSoup

FUZZY_MATCH_THRESHOLD = 0.85


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _quote_is_grounded(quote: str, source_text: str) -> bool:
    norm_quote = _normalize(quote)
    norm_source = _normalize(source_text)
    if not norm_quote:
        return False
    if norm_quote in norm_source:
        return True
    # Fallback: slide a window of similar length across the source and take the
    # best ratio -- catches near-verbatim quotes with e.g. punctuation differences.
    window = len(norm_quote)
    if window == 0 or len(norm_source) < 8:
        return False
    best = 0.0
    step = max(1, window // 4)
    for start in range(0, max(1, len(norm_source) - window + 1), step):
        candidate = norm_source[start : start + window]
        ratio = SequenceMatcher(None, norm_quote, candidate).ratio()
        best = max(best, ratio)
        if best >= FUZZY_MATCH_THRESHOLD:
            return True
    return best >= FUZZY_MATCH_THRESHOLD


@dataclass
class EvidenceCheckResult:
    total_quotes: int
    grounded_quotes: list[str] = field(default_factory=list)
    unverified_quotes: list[str] = field(default_factory=list)

    @property
    def all_grounded(self) -> bool:
        return not self.unverified_quotes


def verify_evidence_quotes(debrief_html: str, transcript_text: str) -> EvidenceCheckResult:
    soup = BeautifulSoup(debrief_html, "html.parser")
    quotes = [bq.get_text(strip=True) for bq in soup.find_all(attrs={"data-evidence": "true"})]
    grounded, unverified = [], []
    for q in quotes:
        (grounded if _quote_is_grounded(q, transcript_text) else unverified).append(q)
    return EvidenceCheckResult(total_quotes=len(quotes), grounded_quotes=grounded, unverified_quotes=unverified)


@dataclass
class NumberCheckResult:
    ok: bool
    mismatches: list[str] = field(default_factory=list)


def verify_synthesis_numbers(brief_html: str, expected_rows: dict[str, tuple[int, int]]) -> NumberCheckResult:
    """expected_rows: {row_label: (col_a_expected, col_b_expected)}

    row_label is matched as a case-insensitive substring of the table row's first
    cell (competitor or segment name). col_a/col_b are e.g. (wins_against, losses_to).
    """
    soup = BeautifulSoup(brief_html, "html.parser")
    mismatches: list[str] = []
    seen_labels: set[str] = set()

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            label = cells[0].strip().lower()
            for expected_label, (expected_a, expected_b) in expected_rows.items():
                if expected_label.lower() not in label:
                    continue
                seen_labels.add(expected_label)
                nums = [int(m) for m in re.findall(r"-?\d+", " ".join(cells[1:3]))]
                if len(nums) < 2 or nums[0] != expected_a or nums[1] != expected_b:
                    mismatches.append(
                        f"{expected_label}: expected ({expected_a}, {expected_b}), "
                        f"found row cells {cells}"
                    )

    for expected_label in expected_rows:
        if expected_label not in seen_labels:
            mismatches.append(f"{expected_label}: no matching table row found in brief")

    return NumberCheckResult(ok=not mismatches, mismatches=mismatches)
