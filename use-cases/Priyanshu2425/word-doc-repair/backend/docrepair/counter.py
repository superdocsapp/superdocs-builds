"""The styling counter's pure logic — the part that has to run before a
network call is even considered, and the part that checks what came back.

`docs/PRD-SET-IT-YOUR-WAY.md` §3 amends **B20** to B20′: a styled file is
refused if its word multiset differs from its **authorised baseline**, and the
authorised baseline is the rebuild's own words, plus words the person supplied
verbatim in this session, minus words they asked removed. Only the person
moves the baseline, and only by supplying the exact text — never by asking the
model to write some.

**B20''** then reopened it for the counter, on 2026-08-26: there the person is
driving, and what they ask SuperDocs for is theirs to ask. So the two halves
of this module now do different jobs —

* `why_refused_before_sending` is the pre-flight layer (PRD §4). It no longer
  looks at what was asked for at all. What remains are the limits: the turn
  cap, and an exhausted allowance — which decides whether to send and is
  never itself described to the person.
* `describe_change` is what replaced the counter's refusal: it reports what a
  turn did to the wording rather than throwing the turn away for it. The rule
  that survives is not "the document may not change", it is "nothing changes
  silently".
* `why_not_acceptable_against` is the guard (PRD §3, §4): the same shape as
  the automatic pass's `superdocs_client._why_not_acceptable`, except the file
  that comes back is checked against the **authorised baseline** rather than
  against the bytes that were sent, because a conversation is allowed to have
  moved the baseline since then.

Stdlib only at module scope, on purpose: this has to be importable without
`requests` installed. The helpers that do know about `.docx` bytes
(`_words`, `docx_text`, `_picture_count`) live in `superdocs_client` and are
imported lazily, inside the functions that need them — the same house style
`superdocs_client.style` already uses for its own lazy imports, and it is
what avoids an import cycle, since `superdocs_client` imports this module
lazily too.
"""

from __future__ import annotations

import re
from collections import Counter

# -- the authorised baseline --------------------------------------------------


def baseline_from(rebuild: bytes) -> Counter:
    """The words the rebuild actually contains. The starting authorised
    baseline, before the person has supplied or removed anything."""
    from .superdocs_client import _words, docx_text

    return Counter(_words(docx_text(rebuild)))


def with_supplied(base: Counter, added: str = "", removed: str = "") -> Counter:
    """`base` + `words(added)` - `words(removed)`. Never goes negative — a
    person cannot remove more of a word than the baseline, or their own prior
    turns, actually put there."""
    from .superdocs_client import _words

    result = Counter(base)
    if added:
        result.update(_words(added))
    if removed:
        result.subtract(_words(removed))
    # Counter's unary `+` keeps only strictly-positive counts, which is
    # exactly "never goes negative" — a word driven to zero or below simply
    # stops being part of the baseline.
    return +result


# -- reading what the person actually supplied --------------------------------

#: A letter or digit — used to keep an apostrophe inside a word (don't,
#: it's, can't) from ever being read as a quote mark. `[^\W_]` is a Unicode
#: word character minus the underscore, i.e. exactly "letter or digit".
_ALNUM = r"[^\W_]"

#: Straight double, straight single, and the two typographic quote pairs the
#: PRD names. Checked in this order only for readability; every pattern is
#: tried and the longest capture wins, so the order here does not bias which
#: quote style is preferred.
#:
#: Double quotes are unambiguous — nobody's contraction opens with `"` — so
#: they are matched plainly. Single quotes are not: a straight or
#: typographic apostrophe sits inside ordinary words far more often than it
#: opens a quotation. A single-quoted run counts only when its opening mark
#: is not preceded by a letter or digit and its closing mark is not followed
#: by one, so "don't make the headings bigger" can never be misread as a
#: person supplying the word "t make the headings bigger" — a contraction
#: must never be mistaken for the person supplying words.
_QUOTE_PATTERNS = (
    re.compile(r'"([^"]+)"'),
    re.compile(rf"(?<!{_ALNUM})'([^']+)'(?!{_ALNUM})"),
    re.compile(r"“([^”]+)”"),
    re.compile(rf"(?<!{_ALNUM})‘([^’]+)’(?!{_ALNUM})"),
)


def supplied_text(message: str) -> str:
    """The exact text the person supplied inside quotes, or "" if they
    supplied none. Handles straight double quotes, single quotes, and
    typographic quotes “ ” ‘ ’. Returns the LONGEST quoted run when several
    are present, on the principle that the longer run is more likely to be
    the sentence itself rather than an incidental word."""
    candidates: list[str] = []
    for pattern in _QUOTE_PATTERNS:
        candidates.extend(pattern.findall(message))
    if not candidates:
        return ""
    return max(candidates, key=len)


# -- pre-flight: the limits, before anything is sent ---------------------------
#
# What used to live here was a prose detector: a table of verbs (finish,
# write, summarise, invent...) and a near-miss rule for reword/rephrase, all
# so a turn asking the model to author text could be turned away for free.
# B20'' retired it on 2026-08-26 — at the counter the person is driving, and
# what they ask for is theirs to ask. It is deleted rather than left unused,
# because a table of rules nothing consults is a description of a product
# that no longer exists, and this codebase has been misled by exactly that
# before. `tests/test_counter.py` keeps the messages it used to refuse, so
# the decision is still written down where it can fail.


def no_allowance_left(period: str = "this month") -> str:
    """The one sentence for a ceiling that has been reached.

    Its own function because there are now two ceilings of the same kind on
    different clocks -- SuperDocs meters a month, the relay this build can
    borrow a key from rations a day -- and they are reached in two places:
    here, before anything is sent, and in `superdocs_client.turn`, when the
    number only became readable because the far end refused. Two sentences
    for one situation would drift, and the person would be told two different
    things about the same "no".

    What they are told does not name the mechanism either way. Somebody whose
    file broke this morning did not arrive with an account, and a number
    describing our metering is not something they can act on.
    """
    return (f"No more changes can be made here {period}. Your document is "
            "unchanged and still yours to download.")


def why_refused_before_sending(message: str, *, turns_left: int,
                               allowance_known: bool,
                               allowance_remaining: int,
                               period: str = "this month") -> str:
    """"" when the turn may be sent. Otherwise ONE consumer-facing sentence.

    Both remaining reasons are limits rather than judgements about what was
    asked for: the turn cap needs no read at all, and the allowance is a
    number already in hand. Neither is described to the person in those
    terms — what they get is one sentence saying no more changes can be made
    here, and that their document is unchanged.
    """
    if turns_left <= 0:
        return ("That is the tenth change on this document, which is as "
                "many as one recovery carries. Your document is unchanged "
                "and still yours to download.")

    # The allowance is still read before anything is sent (B22, and an
    # allowance nobody could read is never treated as a zero one) -- it just
    # is not something a person is told about. Somebody whose file broke did
    # not come here with an account, and has no use for a number that
    # describes ours.
    if allowance_known and allowance_remaining < 1:
        # `period` is which clock ran out -- the month SuperDocs meters, or
        # the day the relay rations. Defaulted rather than required so every
        # existing caller keeps saying exactly what it said before.
        return no_allowance_left(period)

    # No content check here any more. The owner's call, 2026-08-26: at the
    # counter the person is driving, and what they choose to ask SuperDocs
    # for is theirs to ask. The automatic pass keeps its guard, because that
    # is where the model acts with nobody watching; this is where somebody
    # is. What a turn changed is still reported -- see `describe_change` --
    # because "allowed" was never the same as "unremarked".
    return ""


# -- the guard: what came back -------------------------------------------------


def why_not_acceptable_against(sent: bytes, got: bytes,
                               authorised: Counter) -> str:
    """"" when the returned file may be handed over, else the reason it may
    not.

    Same two checks as `superdocs_client._why_not_acceptable` — pictures,
    then words — reusing its own picture and text helpers rather than
    reimplementing them. The one difference is B20′: the word check compares
    what came back against the **authorised baseline**, not against the bytes
    that were sent, because a conversation may have moved that baseline since
    the previous turn.
    """
    from .superdocs_client import _picture_count, _words, docx_text

    before, after = _picture_count(sent), _picture_count(got)
    if after < before:
        return f"with {before - after} fewer pictures than it was sent"

    got_words = Counter(_words(docx_text(got)))
    added = sum((got_words - authorised).values())
    removed = sum((authorised - got_words).values())
    if added + removed:
        return f"with the wording changed ({added} added, {removed} removed)"
    return ""


def describe_change(sent: bytes, got: bytes, authorised: Counter) -> str:
    """What a turn actually did to the document, in one clause, or "".

    The counter no longer refuses a change for altering the wording — the
    owner's decision on 2026-08-26, recorded in `BASELINE.md` at B20″. It
    still says what happened, every time. The rule this build has always kept
    is not "the document may not change"; it is "nothing changes silently",
    and that one survives the refusal being lifted.

    Measured against the authorised baseline, so words the person supplied
    themselves are not reported back to them as a surprise.
    """
    from .superdocs_client import _picture_count, _words, docx_text

    notes: list[str] = []

    before, after = _picture_count(sent), _picture_count(got)
    if after < before:
        gone = before - after
        notes.append(f"{gone} picture{'' if gone == 1 else 's'} no longer in it")

    got_words = Counter(_words(docx_text(got)))
    added = sum((got_words - authorised).values())
    removed = sum((authorised - got_words).values())
    if added:
        notes.append(f"{added} word{'' if added == 1 else 's'} added")
    if removed:
        notes.append(f"{removed} word{'' if removed == 1 else 's'} removed")

    return ", ".join(notes)
