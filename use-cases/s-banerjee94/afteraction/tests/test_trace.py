"""The traceability pass must catch what it claims to catch.

These are the tests that matter most: a verifier that only ever returns "clean" is
worse than no verifier, because it launders unchecked prose as checked. So every test
here proves a *failure* is caught, not that a success passes.
"""

from __future__ import annotations

import pytest

from afteraction.corpus import load_corpus
from afteraction.facts import TIMELINE, build_facts
from afteraction.trace import MAX_SPAN, Verdict, citation_spans, verify


@pytest.fixture(scope="module")
def facts():
    return build_facts(load_corpus("storm-a"))


def test_well_formed_claim_is_traced(facts):
    report = verify("Crews were dispatched at 19:05 [EL-0005].", facts, TIMELINE, allowed=["EL-0005"])
    assert report.clean
    assert report.traced == 1


def test_citation_to_a_nonexistent_entry_is_a_phantom(facts):
    report = verify("The substation was rebuilt overnight [EL-9999].", facts, TIMELINE, allowed=["EL-0005"])
    assert not report.clean
    assert report.results[0].verdict is Verdict.PHANTOM
    assert report.results[0].offending == ["EL-9999"]


def test_citation_outside_the_sections_allowance_is_foreign(facts):
    """EL-0019 exists, but a section never given it has no business citing it."""
    report = verify("A crew was injured at Ashcombe [EL-0019].", facts, TIMELINE, allowed=["EL-0005"])
    assert report.results[0].verdict is Verdict.FOREIGN
    assert report.results[0].offending == ["EL-0019"]


def test_a_bare_assertion_is_unsourced(facts):
    report = verify("Restoration was completed ahead of schedule.", facts, TIMELINE, allowed=["EL-0005"])
    assert report.results[0].verdict is Verdict.UNSOURCED


def test_marked_judgement_is_not_a_traceability_failure(facts):
    report = verify("The response was proportionate to the damage [assessed].", facts, TIMELINE)
    assert report.clean
    assert report.checked == 0  # judgement is not a claim about the record


def test_declared_absence_is_not_a_traceability_failure(facts):
    report = verify("No customer count exists for this window [no record].", facts, TIMELINE)
    assert report.clean


def test_a_trailing_citation_covers_its_own_sentence_group(facts):
    """A citation closing a passage covers that passage, as in ordinary prose."""
    narrative = "Storm room activated at Level 3. Fourteen crews were placed on standby [EL-0002]."
    report = verify(narrative, facts, TIMELINE, allowed=["EL-0002"])
    assert report.clean
    assert report.checked == 1


def test_one_citation_cannot_absolve_an_unbounded_passage(facts):
    """The hole this closed: ten uncited assertions plus one bracket at the end used to
    pass as fully traced. A citation covers at most MAX_SPAN sentences."""
    filler = " ".join(f"Unsupported assertion number {n}." for n in range(10))
    report = verify(f"{filler} Crews were dispatched [EL-0005].", facts, TIMELINE, allowed=["EL-0005"])
    assert not report.clean
    assert any(r.verdict is Verdict.UNSOURCED for r in report.results)


def test_a_citation_does_not_reach_across_a_paragraph_break(facts):
    """Paragraph one asserts without evidence; paragraph two's citation is not its alibi."""
    narrative = "The outage was contained quickly.\nCrews were dispatched at 19:05 [EL-0005]."
    report = verify(narrative, facts, TIMELINE, allowed=["EL-0005"])
    assert not report.clean
    assert report.results[0].verdict is Verdict.UNSOURCED


def test_citation_spans_caps_at_max_span():
    sentences = [f"Sentence {n}." for n in range(MAX_SPAN + 2)] + ["Cited sentence [EL-0001]."]
    units = citation_spans(sentences)
    assert len(units) == 2
    assert units[1].count(".") == MAX_SPAN  # the citation carries only its own neighbours


def test_summary_reports_real_numbers(facts):
    report = verify(
        "Crews dispatched [EL-0005]. Something invented [EL-9999].",
        facts,
        TIMELINE,
        allowed=["EL-0005"],
    )
    assert "1/2" in report.summary()
    assert "do not exist" in report.summary()
