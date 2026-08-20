"""Attributing a change to the rule that motivated it.

The card asks batch mode to report "the violation profile by rule so the team can see
which guidance is being ignored most". That needs every finding to name a rule.

The live API does not give us one. Captured 2026-08-19: a pending change carries
`change_id`, `chunk_id`, `old_html`, `new_html` and an `ai_explanation` written by
SuperDocs itself ("Parallel edit: Linting per style guide."). There is no field for
the caller's rule id, and asking the model to include one in the instruction did not
put it anywhere the response could carry it.

So attribution is done here, deterministically, from triggers the guide declares:

    - `plain-verbs: utilize, initiate, terminate`

That keeps the rules in the attachment where the card wants them — a different guide
declares different triggers and the profile changes with no code edit — and it makes
attribution reproducible rather than another thing a model might get wrong.
"""

from __future__ import annotations

import re

# A trigger line inside the guide: `rule-id: word, phrase, ...`
_TRIGGER = re.compile(r"`([a-z0-9][a-z0-9-]*)\s*:\s*([^`]+)`")
_TRIGGER_SECTION = re.compile(r"##\s*Rule triggers(.*?)(?=\n##\s|\Z)", re.S | re.I)

UNATTRIBUTED = "unattributed"


def triggers(guide_text: str) -> dict[str, tuple[str, ...]]:
    """Rule id -> the words and phrases that fire it, as declared in the guide."""
    section = _TRIGGER_SECTION.search(guide_text)
    if not section:
        return {}
    found: dict[str, tuple[str, ...]] = {}
    for rule, raw in _TRIGGER.findall(section.group(1)):
        words = tuple(w.strip().lower() for w in raw.split(",") if w.strip())
        if words:
            found[rule] = words
    return found


def _count(haystack: str, needle: str) -> int:
    return len(re.findall(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack, re.I))


def attribute(original: str, replacement: str,
              declared: dict[str, tuple[str, ...]],
              case_rule: str | None = None) -> str:
    """Which rule this edit satisfies.

    A trigger counts only if the edit actually *removed* occurrences of it. A word
    that appears equally either side was not what the fix was about, and attributing
    to it would put the finding under the wrong heading in the profile.

    The most specific trigger wins, so "in order to" beats "to".
    """
    best: tuple[int, str] | None = None
    for rule, words in declared.items():
        for word in words:
            removed = _count(original, word) - _count(replacement, word)
            if removed > 0 and (best is None or len(word) > best[0]):
                best = (len(word), rule)
    if best:
        return best[1]

    # No trigger fired. A change that alters only capitalisation is a heading-case
    # fix, which no word list can express.
    if case_rule and original != replacement and original.lower() == replacement.lower():
        return case_rule
    return UNATTRIBUTED
