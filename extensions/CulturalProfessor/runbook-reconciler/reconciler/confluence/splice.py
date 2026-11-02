"""Replace one range of a document and prove nothing else moved.

Confluence has no per-block PATCH. An update is a whole-page `PUT` carrying the
entire body and an incremented version number, so "nothing else changed" cannot
be delegated to the API — the API cannot tell the difference between a one-word
fix and a page somebody's editor reformatted on save.

It is guaranteed by construction instead:

1. the storage-format body is parsed **only to find offsets**;
2. the replacement is spliced into the original string at those offsets;
3. everything outside the splice is byte-identical because it was never
   re-serialized — including macros this tool does not understand;
4. and before any write, `assert_single_change` diffs old against new and
   refuses unless exactly one contiguous range differs and it is the intended
   one.

Step 4 is not paranoia about steps 1–3. It is the check that survives a bug in
them. A splice is a two-integer operation and integers are exactly the thing a
refactor gets wrong quietly; the assertion turns "wrote over half a page" into
"refused to write" without anybody having to notice.

Everything in this module is pure. The version-checked PUT lives in `client.py`,
because a function that can both compute and transmit is one somebody will
eventually call in a test.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise


class SpliceRefused(RuntimeError):
    """The edit was not what it claimed to be, so it was not sent."""


@dataclass(frozen=True)
class Change:
    """One contiguous difference between two versions of a body."""

    start: int
    end_old: int
    end_new: int
    old_text: str
    new_text: str

    @property
    def length_delta(self) -> int:
        return len(self.new_text) - (self.end_old - self.start)


def splice(body: str, start: int, end: int, replacement: str) -> str:
    """The whole edit primitive. Deliberately this small."""
    if not 0 <= start <= end <= len(body):
        raise SpliceRefused(f"range {start}:{end} is outside a body of {len(body)} characters")
    return body[:start] + replacement + body[end:]


def diff_range(old: str, new: str) -> Change | None:
    """The single changed range, found from both ends.

    Common prefix, then common suffix, and what is left in the middle is the
    change. If the two strings differ in more than one place the middle
    contains all of it, which is exactly what `assert_single_change` then
    rejects — this function does not need to be clever to make that work.
    """
    if old == new:
        return None

    start = 0
    limit = min(len(old), len(new))
    while start < limit and old[start] == new[start]:
        start += 1

    tail = 0
    while tail < (limit - start) and old[len(old) - 1 - tail] == new[len(new) - 1 - tail]:
        tail += 1

    return Change(
        start=start,
        end_old=len(old) - tail,
        end_new=len(new) - tail,
        old_text=old[start : len(old) - tail],
        new_text=new[start : len(new) - tail],
    )


def assert_single_change(old: str, new: str, expected_start: int, expected_end: int) -> Change:
    """Refuse to proceed unless exactly the intended range differs.

    The bounds check is deliberately loose at one end and strict at the other:
    the changed range must *begin* no earlier than the intended range and end no
    later than it, but it may be smaller. A replacement sharing a prefix with
    what it replaces — `800ms` becoming `1200ms` — legitimately reports a change
    starting three characters in, and demanding exact equality here would reject
    correct edits and teach whoever hit it to delete the assertion.
    """
    change = diff_range(old, new)
    if change is None:
        raise SpliceRefused("nothing changed; refusing to write a no-op version")
    if change.start < expected_start or change.end_old > expected_end:
        raise SpliceRefused(
            f"the change spans {change.start}:{change.end_old}, which reaches outside the "
            f"approved passage at {expected_start}:{expected_end}. Refusing to write."
        )
    return change


def changed_ranges(old: str, new: str) -> list[Change]:
    """Every contiguous difference, not just the first.

    `diff_range` collapses a document with two edits in it into one enormous
    range spanning both, which is the right behaviour for refusing a single
    write and useless for describing a page that legitimately received three
    approved fixes. `SequenceMatcher` gives the real answer, and the count is
    what the end-of-page assertion checks: **a page that received three
    approvals must differ in exactly three places.**
    """
    from difflib import SequenceMatcher

    out: list[Change] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        out.append(
            Change(start=i1, end_old=i2, end_new=j2, old_text=old[i1:i2], new_text=new[j1:j2])
        )
    return out


def assert_only_these_ranges_changed(old: str, new: str, edits: list[tuple[int, int, str]]) -> None:
    """Everything outside the approved passages is byte-identical. Exactly.

    The last thing checked before a page is sent, and the one that catches what
    the per-splice assertions cannot: an off-by-one in the *order* the splices
    were applied, which corrupts a later offset without any single splice
    looking wrong on its own.

    This started life as "the page must differ in exactly N places", counted
    with `difflib`. That is not the same statement and it does not hold: a
    character-level diff of `rollback-production` → `manual-rollback` reports
    three opcodes, because the two strings share `ll`, `back` and `o`. One
    logical edit, three ranges, and an assertion that refuses a correct write —
    which is the kind of assertion somebody deletes rather than fixes.

    So this reconstructs instead of counting. Given the edits that were meant to
    happen, in old-body coordinates, every byte between them must survive
    unchanged. There is nothing to tune and nothing to be clever about.
    """
    ordered = sorted(edits)
    for (a_start, a_end, _), (b_start, _, _) in pairwise(ordered):
        if a_end > b_start:
            raise SpliceRefused(
                f"approved passages {a_start}:{a_end} and {b_start}:… overlap; "
                f"refusing to write a page whose edits collide"
            )

    old_at = new_at = 0
    for start, end, replacement in ordered:
        gap = start - old_at
        if old[old_at:start] != new[new_at : new_at + gap]:
            raise SpliceRefused(
                f"the document changed between {old_at} and {start}, outside every "
                f"approved passage. Refusing to write."
            )
        if new[new_at + gap : new_at + gap + len(replacement)] != replacement:
            raise SpliceRefused(
                f"the passage at {start}:{end} does not hold the approved replacement. "
                f"Refusing to write."
            )
        old_at, new_at = end, new_at + gap + len(replacement)

    if old[old_at:] != new[new_at:]:
        raise SpliceRefused(
            "the document after the last approved passage is not byte-identical. "
            "Refusing to write."
        )


def assert_untouched_outside(old: str, new: str, start: int, end: int) -> None:
    """The same promise stated the other way round, for the test that proves it.

    `assert_single_change` asks "is the difference inside the passage". This
    asks "is everything outside the passage identical", which is the sentence
    the README makes to a reader. Two spellings of one guarantee, and having
    both means the README's claim is checkable without reading a diff algorithm.
    """
    if old[:start] != new[:start]:
        raise SpliceRefused("the document before the passage is not byte-identical")
    tail_old, tail_new = old[end:], new[len(new) - (len(old) - end) :]
    if tail_old != tail_new:
        raise SpliceRefused("the document after the passage is not byte-identical")


__all__ = [
    "Change",
    "SpliceRefused",
    "assert_single_change",
    "assert_untouched_outside",
    "diff_range",
    "splice",
]
