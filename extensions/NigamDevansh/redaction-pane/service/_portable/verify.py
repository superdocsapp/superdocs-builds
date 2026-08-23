# ─────────────────────────────────────────────────────────────────────
# COPIED FILE — do not edit here.
# Source: packages/core/src/doctask_core/portable/verify.py
# Refresh: uv run python scripts/sync_portable.py
# This app is standalone by design and imports nothing outside itself.
# ─────────────────────────────────────────────────────────────────────
"""Gate 1 — verbatim grounding.

PORTABLE: zero internal imports, standard library only.
Source of truth. Copies live in each extension's `_portable/`.

Three lines of logic on purpose: no model, no fuzzy matching, no threshold. The
"never bluffs" property reduces to — the model said the source says X at
[start, end); we look, and if the bytes there are not X, the claim is dropped.
Checkable in one read, which is the point.

See docs/CORE_INTERNALS.md § "portable/verify.py — Gate 1".
"""

from __future__ import annotations


def verify_quote(extracted_text: str, start: int, end: int, quote: str) -> bool:
    """True when `quote` sits exactly at [start, end) in `extracted_text`.

    The range is checked BEFORE the slice, because Python slicing is lenient in
    three ways that each let a false claim through: a negative `start` addresses
    a different part of the document; `start > end` slices to `""` so a fact with
    no quote passes; an `end` past the string clamps, accepting a citation
    running past the end. Each would become a highlight drawn somewhere other
    than where the fact says it came from.
    """
    if not quote:
        return False
    if not 0 <= start < end <= len(extracted_text):
        return False
    return extracted_text[start:end] == quote


def find_quote(extracted_text: str, quote: str) -> tuple[int, int] | None:
    """Locate an unambiguous quote, for when a model gives text but no offsets.
    Returns None if absent OR appearing more than once — guessing between two
    occurrences would reintroduce the uncertainty this removes.

    Falls back to a whitespace-insensitive search, the one concession here: not
    fuzzy matching (every non-whitespace character still matches, in order, still
    exactly once), only the whitespace between them may differ. Without it a
    quote that IS verbatim fails on any document with newlines inside sentences
    — measured: thirteen present facts dropped across four SEC-filed contracts.
    """
    first = extracted_text.find(quote)
    if first != -1:
        if extracted_text.find(quote, first + 1) != -1:
            return None
        return first, first + len(quote)
    return _find_ignoring_whitespace(extracted_text, quote)


def _find_ignoring_whitespace(extracted_text: str, quote: str) -> tuple[int, int] | None:
    """The same search with every run of whitespace as one space. Offsets come
    back in the original text's coordinates (`positions` keeps the map), or a
    highlight would land at collapsed coordinates in the wrong place."""
    wanted = " ".join(quote.split())
    if not wanted:
        return None

    flat, positions = _collapsed(extracted_text)
    first = flat.find(wanted)
    if first == -1 or flat.find(wanted, first + 1) != -1:
        return None
    return positions[first], positions[first + len(wanted) - 1] + 1


def _collapsed(text: str) -> tuple[str, list[int]]:
    """`(collapsed text, index of each collapsed character in the original)`."""
    out: list[str] = []
    positions: list[int] = []
    in_space = True  # leading whitespace is dropped, as `split()` would
    for index, character in enumerate(text):
        if character.isspace():
            if not in_space:
                out.append(" ")
                positions.append(index)
                in_space = True
        else:
            out.append(character)
            positions.append(index)
            in_space = False
    while out and out[-1] == " ":
        out.pop()
        positions.pop()
    return "".join(out), positions
