"""Claim-to-source span resolution — grounds LLM claims in document text.

LLMs routinely paraphrase when reporting claims ("Loan Reference is
MFL-770487" for source text "Loan Reference: MFL-770487"), so exact
substring lookup alone marks perfectly supported claims as unverifiable.

resolve_span() upgrades resolution through three strategies:

1. Exact substring match.
2. Normalized match (case-insensitive, whitespace-collapsed) with
   position mapping back to the original text.
3. Token-anchor match: significant claim tokens (IDs, amounts, dates,
   names — stopwords dropped) are located in the source; the window
   containing the most distinct tokens wins. A span is returned only
   when a supermajority of the claim's tokens match, so generic or
   hallucinated claims still degrade to unverifiable.

All offsets are character offsets into the ORIGINAL source text.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

# Filler words that carry no locating signal (claim-side only)
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "is", "are", "was", "were", "of", "to", "for",
        "on", "in", "at", "by", "with", "from", "as", "and", "or", "be",
        "been", "being", "shall", "this", "that", "its", "it", "per",
    }
)

# Numbers stay whole: "15.70%", "37,967.53", "1,234" are single tokens,
# so grounded spans don't truncate before a "%" or mid-amount.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*%?")

# Minimum fraction of a claim's significant tokens that must appear in
# the matched source window for the claim to count as grounded.
_MATCH_RATIO_THRESHOLD = 0.6

# A claim must carry at least this many significant tokens to be
# groundable — fewer could match almost anywhere in the document.
_MIN_SIGNIFICANT_TOKENS = 2


def resolve_span(claim_text: str, source_text: str) -> Optional[tuple[int, int]]:
    """Resolve a claim's span in the source text, or None if unverifiable.

    Returns (start, end) character offsets into source_text.
    """
    if not claim_text or not source_text:
        return None

    # Strategy 1: exact match
    idx = source_text.find(claim_text)
    if idx != -1:
        return (idx, idx + len(claim_text))

    # Strategy 2: normalized match (collapse whitespace, case-insensitive)
    normalized_quote = _normalize_for_matching(claim_text)
    if len(normalized_quote) >= 3:
        normalized_source = _normalize_for_matching(source_text)
        norm_idx = normalized_source.find(normalized_quote)
        if norm_idx != -1:
            original_start = _map_normalized_pos_to_original(source_text, norm_idx)
            original_end = _map_normalized_pos_to_original(
                source_text, norm_idx + len(normalized_quote)
            )
            if original_start < original_end:
                return (original_start, original_end)

    # Strategy 3: token-anchor match (handles paraphrase)
    return _token_anchor_span(claim_text, source_text)


def _normalize_for_matching(text: str) -> str:
    """Collapse whitespace and lowercase for fuzzy span matching."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _map_normalized_pos_to_original(original: str, normalized_pos: int) -> int:
    """Map a character position in normalized text back to the original text.

    Walks through the original text, counting non-collapsed characters
    until we reach the target normalized position.
    """
    norm_count = 0
    in_whitespace = False
    i = 0

    # Skip leading whitespace in original (normalized strips leading)
    while i < len(original) and original[i] in " \t\n\r":
        i += 1

    while i < len(original) and norm_count < normalized_pos:
        if original[i] in " \t\n\r":
            if not in_whitespace:
                norm_count += 1  # collapsed whitespace counts as 1 char
                in_whitespace = True
        else:
            norm_count += 1
            in_whitespace = False
        i += 1

    return i


def _significant_tokens(text: str) -> list[str]:
    """Distinct alphanumeric tokens of a text, stopwords and 1-char drops."""
    seen: set[str] = set()
    significant: list[str] = []
    for token in _TOKEN_RE.findall(text.lower()):
        if len(token) < _MIN_SIGNIFICANT_TOKENS or token in _STOPWORDS:
            continue
        if token not in seen:
            seen.add(token)
            significant.append(token)
    return significant


def _token_anchor_span(claim_text: str, source_text: str) -> Optional[tuple[int, int]]:
    """Find the source window sharing the most of a claim's significant tokens.

    Returns the char span from the first to the last matched source token,
    or None when fewer than _MATCH_RATIO_THRESHOLD of the claim's tokens
    appear together.
    """
    significant = _significant_tokens(claim_text)
    if len(significant) < _MIN_SIGNIFICANT_TOKENS:
        return None

    source_tokens = list(_TOKEN_RE.finditer(source_text.lower()))
    if not source_tokens:
        return None

    sig_set = set(significant)

    # Inverted index: token → source token positions (for candidates)
    positions_by_token: dict[str, list[int]] = defaultdict(list)
    for i, match in enumerate(source_tokens):
        token = match.group()
        if token in sig_set:
            positions_by_token[token].append(i)

    # Candidate window starts: positions where any claim token occurs
    candidates = sorted(
        {i for positions in positions_by_token.values() for i in positions}
    )
    if not candidates:
        return None

    window = max(3 * len(significant), 8)
    best_key = None
    best_span: Optional[tuple[int, int]] = None

    for start_idx in candidates:
        matched: set[str] = set()
        first = last = None
        for j in range(start_idx, min(start_idx + window, len(source_tokens))):
            token = source_tokens[j].group()
            if token in sig_set and token not in matched:
                matched.add(token)
                if first is None:
                    first = j
                last = j
        score = len(matched)
        # Must clear the ratio bar before competing
        if score == 0 or score / len(significant) < _MATCH_RATIO_THRESHOLD:
            continue
        width_steps = max(last - first, 1)
        # Rank: denser match first (a tight row beats a scattered window
        # that strings together header words), then more matches, then
        # earlier position.
        key = (score / width_steps, score, -start_idx)
        if best_key is None or key > best_key:
            best_key = key
            # Expand outward through adjacent source tokens that are also
            # claim tokens — recovers field labels sitting right before
            # the matched values ("Statement Period: 2023-08-03") without
            # letting the span bleed across unmatched text.
            a, b = first, last
            while a > 0 and source_tokens[a - 1].group() in sig_set:
                a -= 1
            while b + 1 < len(source_tokens) and source_tokens[b + 1].group() in sig_set:
                b += 1
            best_span = (source_tokens[a].start(), source_tokens[b].end())

    return best_span
