"""
Fact-grounding ("hallucination") check for drafted response sections.

`build_response_instruction` already tells the drafting model "do not
invent facts, evidence, or citations that were not given to you" -- this
module is the automated check that a human currently has to do by eye to
verify the model actually followed that instruction: does every specific,
checkable detail (dollar amounts, dates, years-of-experience, named
organizations/people, percentages) that shows up in the DRAFT actually
trace back to something in the SOURCE material (the officer's RFE item
text, the matched prior-petition argument, and the matched evidence-catalog
descriptions)?

This is a heuristic, not a fact-checker: it does substring/near-match
lookups over a small set of regex-extracted "checkable detail" shapes, not
NLI or a second LLM call. It will have false positives (a paraphrased
number, a detail from supporting material not passed to it) and false
negatives (a fabricated claim with no distinctive number/proper-noun
shape). It is deliberately framed everywhere as "worth a human's second
look", exactly like `PriorPetition.fuzzy_matches`/`semantic_matches` --
never as a pass/fail gate that blocks or auto-rejects a draft. A reviewer
still makes the actual approve/reject call; this just narrows what they
need to double-check instead of re-reading the whole section against the
whole record every time.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Each pattern extracts one "shape" of checkable detail. Ordered roughly
# most-specific-first so a single token isn't captured by multiple
# patterns (e.g. "$4,500" shouldn't also separately match the bare-number
# pattern) -- callers dedupe by normalized text regardless, but keeping
# patterns disjoint keeps the matched-fact list readable.
_MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?%")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DURATION_RE = re.compile(r"\b\d+\+?\s+(?:years?|months?|weeks?|days?)\b", re.IGNORECASE)
_COUNT_RE = re.compile(r"\b\d+\s+(?:employees?|projects?|patents?|publications?|clients?|"
                        r"awards?|citations?|case(?:s)?)\b", re.IGNORECASE)
# Two-or-more consecutive capitalized words -- a cheap proper-noun /
# named-entity detector. Deliberately requires 2+ words (not 1) to avoid
# flagging every sentence-initial capitalized word as a "fact".
_PROPER_NOUN_RE = re.compile(r"\b(?:[A-Z][a-zA-Z&.,\'-]*\s+){1,4}[A-Z][a-zA-Z&.,\'-]*\b")

_COMMON_SENTENCE_STARTS = {
    "the", "this", "these", "those", "it", "in", "on", "at", "for", "with", "as", "a", "an",
}

_ALL_PATTERNS: list[re.Pattern] = [_MONEY_RE, _PERCENT_RE, _YEAR_RE, _DURATION_RE, _COUNT_RE]


def _extract_numeric_facts(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in _ALL_PATTERNS:
        for m in pattern.finditer(text):
            found.add(m.group(0).strip())
    return found


def _extract_proper_nouns(text: str) -> set[str]:
    found: set[str] = set()
    for m in _PROPER_NOUN_RE.finditer(text):
        words = m.group(0).strip().split()
        # Strip leading common words rather than discarding the whole
        # match -- a sentence-initial phrase like "At Acme Robotics
        # Corp" would otherwise lose "Acme Robotics Corp" entirely just
        # because "At" got capitalized by sentence position. Only the
        # LEADING common word(s) are stripped; a common word appearing
        # mid-phrase (rare in this shape) is left alone.
        while words and words[0].lower() in _COMMON_SENTENCE_STARTS:
            words = words[1:]
        if len(words) < 2:
            continue
        found.add(" ".join(words))
    return found


def extract_checkable_facts(text: str) -> set[str]:
    """All "checkable detail" shapes found in `text` -- money amounts,
    percentages, years, durations, counts, and 2+ word proper-noun-shaped
    phrases. Used on both the draft (to know what to check) and, via
    `_normalize`, implicitly on the source (to know what's checkable
    against)."""
    return _extract_numeric_facts(text) | _extract_proper_nouns(text)


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


@dataclass
class GroundingResult:
    ungrounded_facts: list[str] = field(default_factory=list)
    total_facts_checked: int = 0

    @property
    def has_concerns(self) -> bool:
        return bool(self.ungrounded_facts)


def check_grounding(draft_text: str, source_texts: list[str]) -> GroundingResult:
    """Extracts checkable facts from `draft_text` and flags any that
    don't appear (case/whitespace-insensitive substring match) anywhere
    in `source_texts` (the RFE item text, the matched prior-petition
    argument text, and the matched evidence-catalog descriptions --
    i.e. everything that was actually given to the drafting model for
    this item). Returns a `GroundingResult` -- always additive
    information for a reviewer, never a reason to auto-reject a draft."""
    if not draft_text or not draft_text.strip():
        return GroundingResult()

    combined_source = _normalize(" ".join(s for s in source_texts if s))
    draft_facts = extract_checkable_facts(draft_text)

    ungrounded = sorted(
        fact for fact in draft_facts
        if _normalize(fact) not in combined_source
    )
    return GroundingResult(ungrounded_facts=ungrounded, total_facts_checked=len(draft_facts))
