"""A translation may change every word and may not change the shape.

The third grading criterion. The failure it guards against is not
mistranslation -- it is that German runs longer than English, so a translated
manual reflows, a step lands on a different page from its diagram, and the
printed card no longer folds where the crease is.
"""
from __future__ import annotations

import re

import pytest

from manualbuilder import localize as lz, projections as pj

from .conftest import PROJECT_ROOT


@pytest.fixture(scope="session")
def german(spec):
    return lz.localised_spec(spec, lz.load_locale(PROJECT_ROOT / "locales" / "de.yaml"))


@pytest.fixture(scope="session")
def french(spec):
    return lz.localised_spec(spec, lz.load_locale(PROJECT_ROOT / "locales" / "fr.yaml"))


def test_both_launch_markets_are_complete(spec, german, french):
    """A half-translated locale silently falls back to English, which is the
    right behaviour and a terrible thing to ship without noticing. Every string
    the two shipped locales are responsible for is checked to have moved."""
    for code, localised in (("de", german), ("fr", french)):
        for step in spec.steps:
            assert localised.step(step.id).body != step.body, f"{code}/{step.id}"
        for warning in spec.warnings:
            assert localised.warning(warning.id).body != warning.body
        for fault in spec.faults:
            assert localised.fault(fault.id).fix != fault.fix
        for statement in spec.statements:
            assert localised.statement(statement.id).body != statement.body


def test_the_german_manual_is_longer_and_shaped_the_same(spec, german):
    """Both halves matter. Identical length would mean nothing was translated;
    a different outline would mean it repaginates."""
    english_html = pj.manual_html(spec)
    german_html = pj.manual_html(german)

    assert len(german_html) > len(english_html) * 1.05, "nothing was translated"
    assert lz.compare_structure(english_html, german_html) == []
    lz.assert_same_structure(english_html, german_html, "de")


def test_the_card_is_localised_too(spec, german):
    english = pj.quick_start_html(spec)
    localised = pj.quick_start_html(german)
    assert "Testmuster" in localised
    assert lz.compare_structure(english, localised) == []


def test_the_localised_card_still_matches_the_localised_manual(german):
    """The consistency guarantee has to survive translation. Both documents are
    projections of the *localised* spec, so the German card carries the German
    manual's sentences -- not a separately translated near-copy of them."""
    manual = pj.manual_html(german)
    card = pj.quick_start_html(german)
    for step in german.quick_start():
        assert step.body in card
        assert step.body in manual


def test_the_drawings_speak_the_locale_too(spec, german, french):
    """A drawing is generated from the parts graph, and a localised spec is that
    graph with German labels in it -- so the German manual gets German diagrams
    from the same renderer rather than English ones with a translation around
    them. The words the drawing puts on *itself* are the ones that get missed:
    printed English is much harder to spot inside an SVG than in a paragraph."""
    from manualbuilder import diagram

    english = diagram.exploded(spec)
    assert "SUPPLIED, NOT MOUNTED" in english

    for localised in (german, french):
        drawn = diagram.exploded(localised)
        assert "SUPPLIED, NOT MOUNTED" not in drawn
        assert "parts breakdown" not in drawn
        for part in localised.parts:
            if part.label != spec.part(part.id).label:
                assert part.label[:18] in drawn


def test_a_locale_cannot_invent_a_diagram_string(spec):
    """Same rule as everywhere else: a locale fills ids that exist. A key nobody
    reads is a translation somebody paid for that never appears."""
    with pytest.raises(lz.LocaleError, match="diagram string 'tagline_footer'"):
        lz.localised_spec(spec, {"language": "xx",
                                 "diagram": {"tagline_footer": "..."}})


def test_a_locale_cannot_add_structure(spec):
    """A locale supplies strings. A locale that names a step the spec does not
    have is a locale adding a section, and a document with an extra section
    paginates differently by definition."""
    with pytest.raises(lz.LocaleError, match="cannot add or rename structure"):
        lz.localised_spec(spec, {
            "language": "fr",
            "steps": {"calibrer_le_flux": {"title": "Calibrer", "body": "..."}},
        })


def test_a_dropped_heading_is_caught(spec, german):
    """The assertion has to actually fire. Deleting one heading from the German
    manual is the smallest structural break that would reflow a page, and it is
    exactly what a translator working in a word processor would do."""
    german_html = pj.manual_html(german)
    # By block id rather than by its words: the heading a translator would
    # delete is the same heading whatever language it is written in.
    broken = re.sub(r'<h2 data-block="sec:specifications">.*?</h2>\n', "",
                    german_html, count=1)
    assert broken != german_html, "the test did not actually remove a heading"

    problems = lz.compare_structure(pj.manual_html(spec), broken)
    assert problems, "a missing heading must be reported"
    with pytest.raises(lz.LocaleError, match="paginate differently"):
        lz.assert_same_structure(pj.manual_html(spec), broken, "de")


def test_a_lost_figure_is_caught(spec, german):
    """A translated manual that dropped a diagram would still read correctly and
    would be missing an illustration on every page after it."""
    broken = pj.manual_html(german).replace("<figure", "<div", 1)
    problems = lz.compare_structure(pj.manual_html(spec), broken)
    assert any("figure" in str(p) for p in problems)


def test_the_outline_ignores_words_entirely(spec, german):
    """The property being defended is shape, not length. If `outline` were
    sensitive to text it would fail every honest translation."""
    assert lz.outline(pj.manual_html(spec)) == lz.outline(pj.manual_html(german))
    assert all(tag.lstrip("/") in lz.STRUCTURE_TAGS
               for tag in lz.outline(pj.manual_html(spec)))


def test_untranslated_strings_fall_back_rather_than_vanishing(spec):
    """A partial locale is normal during translation. A missing string must show
    the source language, never an empty heading -- an empty heading is a
    structural element with nothing in it, which is worse than English."""
    partial = lz.localised_spec(spec, {"language": "fr",
                                       "steps": {"rails": {"title": "Monter les rails"}}})
    assert partial.step("rails").title == "Monter les rails"
    assert partial.step("rails").body == spec.step("rails").body
    assert partial.step("gantry").title == spec.step("gantry").title
    assert lz.compare_structure(pj.manual_html(spec), pj.manual_html(partial)) == []
