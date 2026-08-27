"""Checking that a quoted commitment was really said.

The card's bar is extracting the actual commitments rather than summarising politely,
and the difference between those two is evidence. Every extracted row carries a quote;
this module checks that quote against the words in the thread. A row whose quote cannot
be located is not a commitment, however plausible it reads — it is the model's own prose
wearing quotation marks, and it never reaches the letter.

The check is deliberately dumb string matching over normalised text. Its value is
precisely that it has no opinion and cannot be persuaded: either those words are in the
thread or they are not.

Two allowances, both for how models quote rather than what they claim:

* **Line wrapping.** Mail wraps at seventy-odd characters, so a sentence typed as one
  thought arrives split. Comparison is on whitespace-normalised text.
* **Elision.** A model may quote "we will deliver … by 21 March". Each fragment is
  required, in order. That is still evidence; it just has a gap in the middle.

Neither allowance lets new words in.
"""

from __future__ import annotations

import re

from .commitments import Commitment
from .thread import Thread, normalise

_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…)\s*")
#: Wrapping quotation marks a model adds around the thing it is quoting.
_WRAPPERS = "\"'`«»„“”‘’ \t"

#: A fragment shorter than this proves nothing — "we will" appears in any thread.
MIN_FRAGMENT = 12


def _fragments(quote: str) -> list[str]:
    parts = [p.strip(_WRAPPERS) for p in _ELLIPSIS.split(quote or "")]
    return [normalise(p) for p in parts if normalise(p)]


def locate(thread: Thread, quote: str) -> tuple[bool, int | None, str]:
    """Find a quote in the thread. Returns ``(found, message_index, note)``."""
    fragments = _fragments(quote)
    if not fragments:
        return False, None, "no quote was given"
    if sum(len(f) for f in fragments) < MIN_FRAGMENT:
        return False, None, "the quote is too short to identify anything"

    # Prefer a single message containing every fragment in order: a commitment is
    # something one person said in one message, not a sentence assembled from several.
    for message in thread.messages:
        haystack = message.normalised
        if _contains_in_order(haystack, fragments):
            return True, message.index, ""

    # Fall back to the whole thread, and say so — a quote that spans messages is
    # evidence of something, but not of one person undertaking one thing.
    if _contains_in_order(thread.normalised, fragments):
        return True, None, "found in the thread but not within any single message"

    return False, None, "these words do not appear in the thread"


def _contains_in_order(haystack: str, fragments: list[str]) -> bool:
    cursor = 0
    for fragment in fragments:
        found = haystack.find(fragment, cursor)
        if found == -1:
            return False
        cursor = found + len(fragment)
    return True


def verify(thread: Thread, commitments: list[Commitment]) -> list[Commitment]:
    """Mark every commitment with whether its quote survives checking.

    Nothing is deleted. A row that fails is kept and shown, because "the model claimed
    this and could not back it up" is information the reviewer wants, and quietly
    dropping it would hide the one failure mode worth watching for.
    """
    for c in commitments:
        found, index, note = locate(thread, c.quote)
        c.quote_found = found
        c.located_in = index
        c.quote_note = note
        if found and index is not None and c.source and c.source.isdigit():
            if int(c.source) != index:
                # Not fatal: the words are real, the attribution slipped. Correct it
                # to where the words actually are, and say that we did.
                c.quote_note = (
                    f"attributed to message {c.source}, actually said in message {index}"
                )
                c.source = str(index)
    return commitments


def unsupported(commitments: list[Commitment]) -> list[Commitment]:
    """Rows the model could not back up. Worth a human's attention."""
    return [c for c in commitments if not c.quote_found]
