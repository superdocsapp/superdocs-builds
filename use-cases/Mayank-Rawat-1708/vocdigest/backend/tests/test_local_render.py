"""
@file: backend/tests/test_local_render.py
@description: Tests the local document renderer. Its job is to turn sections that were
    written as *instructions to a document editor* into a document a person reads, so the
    assertions are mostly about instruction text NOT appearing in the output.
@flow: build representative draft sections -> render to Markdown and DOCX -> assert
    headings are clean, the theme table is not duplicated, and no editor phrasing survives.
@dependencies: backend.services.local_render, python-docx
"""

from __future__ import annotations

import pytest

from backend.services.local_render import (
    _deep_dive_keys,
    render_digest,
    render_digest_markdown,
    split_theme_section,
    strip_instruction_framing,
)

SECTIONS = {
    "executive_summary": (
        "Replace the Executive Summary section body with exactly this text, unchanged:\n\n"
        "39 conversations were analysed across 24 themes."
    ),
    "theme_table": (
        "In the 'Top Themes This Quarter' section, insert a table with the columns "
        "Theme, Volume, Share, Change. Use exactly these rows and do not add, reorder, "
        "or invent any:\n\n"
        "| Theme | Volume | Share | Change |\n"
        "| Excel Export Issue | 4 | 10.3% | New this quarter |\n"
        "| Email Notification | 4 | 10.3% | New this quarter |"
    ),
    "theme_1": (
        "Add a subsection under 'Theme Deep Dives' titled 'Excel Export Issue — 4 "
        "conversations (New this quarter)'. Its body must contain, in order:\n\n"
        "Customers reported that Excel export produces an empty file.\n\n"
        "What customers said:\n  - \"Export gives me a zero-byte file\"\n\n"
        "Evidence: 4 conversations. Citations: [1] q3.csv:12\n\n"
        "Do not add commentary, causes, or recommendations beyond this text."
    ),
    "theme_2": (
        "Add a subsection under 'Theme Deep Dives' titled 'Email Notification — 4 "
        "conversations (New this quarter)'. Its body must contain, in order:\n\n"
        "Notification emails are not arriving.\n\n"
        "Evidence: 4 conversations."
    ),
    "methodology": (
        "Replace the 'Methodology' section body with exactly:\n\n"
        "Themes were derived by clustering 39 support conversations."
    ),
}


def test_theme_table_is_not_rendered_as_a_deep_dive():
    """theme_table also starts with "theme_", and was being rendered twice.

    Observed in a real generated document: the markdown header row `| Theme | Volume |
    Share | Change |` appeared as a Heading 2 under Theme Deep Dives, on top of the
    correctly-rendered table above it.
    """
    keys = _deep_dive_keys(SECTIONS)
    assert keys == ["theme_1", "theme_2"]
    assert "theme_table" not in keys


def test_deep_dive_keys_sort_numerically():
    """theme_10 must follow theme_2, not precede it."""
    keys = _deep_dive_keys({f"theme_{i}": "" for i in (1, 2, 10, 11, 3)})
    assert keys == ["theme_1", "theme_2", "theme_3", "theme_10", "theme_11"]


def test_theme_heading_excludes_the_editor_instruction():
    """The heading must be the title, not the whole instruction.

    A real document carried headings reading "Excel Export Issue — 4 conversations
    (New this quarter)'. Its body must contain, in order:" — editor phrasing leaking
    into what a reader sees.
    """
    title, body = split_theme_section(SECTIONS["theme_1"])
    assert title == "Excel Export Issue — 4 conversations (New this quarter)"
    assert "Its body must contain" not in title
    assert "Its body must contain" not in body
    assert "Add a subsection" not in body
    assert "Do not add commentary" not in body
    assert body.startswith("Customers reported")


def test_no_instruction_phrasing_survives_into_markdown():
    """Nothing that addresses a document editor may reach the reader."""
    output = render_digest_markdown(
        SECTIONS, quarter_label="Q3 2026", conversation_count=39, reason="Testing."
    )
    for phrase in (
        "Replace the",
        "Its body must contain",
        "Add a subsection",
        "Use exactly these rows",
        "do not add, reorder, or invent",
        "Do not add commentary",
        "insert a table with the columns",
    ):
        assert phrase not in output, f"instruction phrasing leaked: {phrase!r}"

    # The content itself survives.
    assert "39 conversations were analysed" in output
    assert "Excel Export Issue" in output


def test_docx_headings_are_clean(tmp_path):
    docx_mod = pytest.importorskip("docx")

    result = render_digest(
        SECTIONS,
        tmp_path / "digest.docx",
        quarter_label="Q3 2026",
        conversation_count=39,
        reason="SuperDocs unavailable for this test.",
    )
    document = docx_mod.Document(result["path"])
    headings = [
        p.text for p in document.paragraphs
        if p.style.name.startswith("Heading") or p.style.name == "Title"
    ]

    for heading in headings:
        assert "Its body must contain" not in heading
        assert "Replace the" not in heading
        assert not heading.strip().startswith("|"), (
            f"a table row became a heading: {heading!r}"
        )

    assert "Excel Export Issue — 4 conversations (New this quarter)" in headings
    # The table is a real Word table, rendered once.
    assert len(document.tables) == 1
    assert document.tables[0].rows[0].cells[0].text == "Theme"


def test_local_render_states_its_own_provenance(tmp_path):
    """A locally-rendered document must say so, not pass as a SuperDocs export."""
    docx_mod = pytest.importorskip("docx")

    result = render_digest(
        SECTIONS,
        tmp_path / "d.docx",
        quarter_label="Q3 2026",
        conversation_count=39,
        reason="SUPERDOCS_API_KEY is not configured.",
    )
    body = "\n".join(p.text for p in docx_mod.Document(result["path"]).paragraphs)
    assert "Rendered locally" in body
    assert "SUPERDOCS_API_KEY is not configured" in body


def test_strip_handles_an_unknown_instruction_shape():
    """An unrecognised section must lose its content, not its whole body."""
    title, body = split_theme_section("Some future instruction shape.\n\nReal content here.")
    assert body or title, "content was dropped entirely"
    assert "Real content here." in f"{title}\n{body}"


def test_generic_stripper_leaves_content_intact():
    text = "Replace the Executive Summary section body with exactly:\n\nThe real summary."
    assert strip_instruction_framing(text) == "The real summary."