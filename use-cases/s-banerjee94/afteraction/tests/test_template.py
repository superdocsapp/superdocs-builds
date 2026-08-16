"""The design lives in a file, and the renderer must not quietly work around it.

Styling is inline because that is the only kind SuperDocs keeps. A `<style>` block in the
head is dropped on upload, so a stylesheet would look correct locally and arrive at the
service as an unstyled document — a failure that only shows up in the exported .docx.
These tests hold that boundary, and hold the renderer to failing loudly rather than
shipping a literal `{{slot}}` for the model to draft around.
"""

from __future__ import annotations

import re

import pytest

from afteraction import template as T
from afteraction.corpus import available_events, load_corpus
from afteraction.facts import build_facts
from afteraction.models import Lesson, LessonStatus
from afteraction.sections import skeleton_html

# every block name the report renderer asks the template for
REQUIRED = {
    "document",
    "section",
    "observed",
    "assessed",
    "gaps",
    "curve",
    "carried_heading",
    "raised_heading",
    "carry_table",
    "carry_row",
    "carry_row_shaded",
}


@pytest.fixture(scope="module", params=available_events())
def skeleton(request):
    return skeleton_html(build_facts(load_corpus(request.param)), [])


def test_template_defines_every_block_the_renderer_uses():
    assert REQUIRED <= set(T.blocks())


def test_unknown_block_is_an_error():
    with pytest.raises(T.TemplateError, match="no block named"):
        T.fill("no_such_block")


def test_missing_slot_value_is_an_error_not_a_literal_slot():
    """A `{{body_html}}` reaching SuperDocs would be drafted around as if it were text."""
    with pytest.raises(T.TemplateError, match="body_html"):
        T.fill("section", number="1", title="Event Overview")


def test_value_with_no_slot_is_an_error():
    with pytest.raises(T.TemplateError, match="no slot for"):
        T.fill("curve", caption="unused")


def test_text_values_are_escaped_and_markup_slots_are_not():
    row = T.fill(
        "carry_row",
        item="Crew <b>timing</b>",
        raised_in="storm-a",
        owner="Grid & Metering",
        status="Open",
        note="—",
    )
    assert "&lt;b&gt;timing&lt;/b&gt;" in row
    assert "Grid &amp; Metering" in row

    table = T.fill("carry_table", rows_html=row)
    assert row in table  # the _html suffix means it is markup, kept verbatim


# ------------------------------------------------------------------ the skeleton


def test_skeleton_carries_inline_styles(skeleton):
    assert skeleton.count("style=") > 20


def test_skeleton_has_no_stylesheet(skeleton):
    """SuperDocs drops these on upload, so one here would be a silent loss of design."""
    assert "<style" not in skeleton
    assert "class=" not in skeleton


def test_skeleton_leaves_no_unfilled_slot(skeleton):
    assert "{{" not in skeleton


def test_skeleton_excludes_the_local_preview_chrome(skeleton):
    """Only the marked blocks are uploaded; the page frame stays in the file."""
    for chrome in ("<!doctype", "<html", "<head", "<body", "<!--"):
        assert chrome not in skeleton.lower()


def test_skeleton_keeps_the_headings_the_pipeline_and_mock_look_for(skeleton):
    assert re.search(r"<h2[^>]*>1\. Event Overview</h2>", skeleton)
    assert re.search(r"<h3[^>]*>Observed</h3>", skeleton)
    assert "Placeholder for observed statements." in skeleton
    assert "Placeholder for the restoration curve." in skeleton


def test_carry_table_shades_alternate_rows():
    """Zebra striping is the one thing a five-column status table needs to stay readable,
    and it survives to Word as cell shading rather than as a stylesheet rule."""
    lessons = [
        Lesson(
            lesson_id=f"LL-A{n}",
            title=f"Item {n}",
            detail=f"Detail for item {n}.",
            owner="Control Room",
            opened_in_event="storm-a",
            status=LessonStatus.OPEN,
            sources=["EL-0004"],
        )
        for n in range(1, 4)
    ]
    facts = build_facts(load_corpus("storm-a"))
    html = skeleton_html(facts, lessons)
    rows = re.findall(r"<tr>\s*<td[^>]*>LL-A\d[^<]*</td>", html)
    assert len(rows) == 3
    assert [("background-color" in r) for r in rows] == [False, True, False]
