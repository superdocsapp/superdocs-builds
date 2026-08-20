"""Rule attribution — the piece that makes the batch profile mean anything.

The live API carries no rule id on a proposed change, so attribution is derived from
triggers the guide declares. These tests fix the behaviour that matters: the rule
must live in the guide, the most specific trigger must win, and a word that was not
actually removed must not be credited.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stylefix.parsing import parse_proposed_changes  # noqa: E402
from stylefix.rules import UNATTRIBUTED, attribute, triggers  # noqa: E402

HOUSE = (ROOT / "styleguides" / "house-product-style.md").read_text(encoding="utf-8")
PLAIN = (ROOT / "styleguides" / "plain-english-public.md").read_text(encoding="utf-8")


def test_triggers_are_read_from_the_guide():
    declared = triggers(HOUSE)
    assert "plain-verbs" in declared and "utilize" in declared["plain-verbs"]


def test_two_guides_declare_different_rules():
    """Attribution changes with the guide, not with the code."""
    assert set(triggers(HOUSE)) != set(triggers(PLAIN))
    assert "no-latin" in triggers(PLAIN)


def test_a_guide_with_no_trigger_section_declares_nothing():
    assert triggers("# A guide\n\nProse only, no triggers.\n") == {}


def test_removed_word_is_attributed():
    assert attribute("terminate the session", "end the session",
                     triggers(HOUSE)) == "plain-verbs"


def test_most_specific_trigger_wins():
    """'in order to' must beat a shorter trigger inside the same edit."""
    declared = triggers(HOUSE)
    assert attribute("In order to click Save", "To click Save", declared) == "no-filler"


def test_a_word_that_survived_the_edit_is_not_credited():
    """The fix was not about 'please' if 'please' is still there afterwards."""
    got = attribute("please utilize the cache", "please use the cache", triggers(HOUSE))
    assert got == "plain-verbs"


def test_case_only_change_is_attributed_to_the_heading_rule():
    got = attribute("The Webhook", "the webhook", triggers(HOUSE),
                    case_rule="sentence-case-headings")
    assert got == "sentence-case-headings"


def test_nothing_matching_is_honestly_unattributed():
    assert attribute("alpha", "beta", triggers(HOUSE)) == UNATTRIBUTED


def test_attribution_against_the_live_payload():
    """The real changes from 2026-08-19, attributed from the guide."""
    job = json.loads((ROOT / "tests" / "fixtures" /
                      "get_job_awaiting_approval.json").read_text(encoding="utf-8"))
    declared = triggers(HOUSE)
    got = {c.change_id[:8]: attribute(c.original, c.replacement, declared,
                                      "sentence-case-headings")
           for c in parse_proposed_changes(job)}
    assert got == {"cc3f6a9a": "sentence-case-headings",
                   "70f6040c": "no-filler",
                   "ea2646be": "plain-verbs"}
