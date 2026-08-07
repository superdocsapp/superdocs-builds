"""Section-level diffing: the machinery behind every "nothing else changed" claim.

These are behaviour tests, not mock tests. Two of them are built from documents
the live API actually returned - the corrupted one from bugs.md B2 and the
div-wrapped section from B12 - so they test the real failure, not my idea of it.
"""

from pathlib import Path

import pytest

from superdocs_kit.docdiff import (
    chunk_map,
    diff_chunks,
    residue_map,
    section_html,
    section_named,
    sections,
    table_rows,
    text_diff,
    verify_surgical,
    visible_text,
)

REPRO = Path(__file__).resolve().parent.parent / "repro"

DOC = (
    '<h1 data-chunk-id="h0">Digest</h1>'
    '<h2 data-chunk-id="h1">What changed</h2>'
    '<ul data-chunk-id="u1"><li>alpha</li><li>beta</li></ul>'
    '<h2 data-chunk-id="h2">At risk</h2>'
    '<table data-chunk-id="t1" style="border:1px">'
    '<tr data-chunk-id="r1"><td data-chunk-id="d1">Audio</td></tr>'
    '<tr data-chunk-id="r2"><td data-chunk-id="d2">Art</td></tr></table>'
    '<h2 data-chunk-id="h3">Archive</h2><p data-chunk-id="p3">w01</p>'
)


def test_chunk_map_captures_exact_outer_html_including_nesting():
    m = chunk_map(DOC)
    assert set(m) == {"h0", "h1", "u1", "h2", "t1", "r1", "d1", "r2", "d2", "h3", "p3"}
    assert m["t1"].startswith("<table") and m["t1"].endswith("</table>")
    assert m["d1"] == '<td data-chunk-id="d1">Audio</td>'


def test_editing_a_cell_does_not_report_its_row_and_table_as_changed():
    """Without this, one cell edit looks like three changed sections and the
    surgical check drowns in false positives."""
    after = DOC.replace(">Audio<", ">Audio middleware<")
    assert diff_chunks(DOC, after).modified == ["d1"]


def test_a_container_whose_own_bytes_change_is_still_reported():
    """The sibling of the case above: it must not over-suppress."""
    after = DOC.replace(">Audio<", ">Audio middleware<").replace('style="border:1px"',
                                                                 'style="border:3px"')
    assert set(diff_chunks(DOC, after).modified) == {"d1", "t1"}


def test_residue_map_blanks_descendants():
    res = residue_map(DOC)
    assert "Audio" not in res["t1"]          # the cell's bytes are blanked out
    assert "border:1px" in res["t1"]         # the table's own bytes are not


def test_verify_surgical_passes_when_only_the_named_section_moved():
    after = DOC.replace(">Audio<", ">Audio middleware<")
    v = verify_surgical(DOC, after, expected_sections=["At risk"])
    assert v.ok and not v.unintended


def test_verify_surgical_fails_when_another_section_moved():
    after = DOC.replace(">alpha<", ">gamma<")
    v = verify_surgical(DOC, after, expected_sections=["At risk"])
    assert not v.ok and v.unintended == ["u1"]


def test_verify_surgical_counts_byte_identical_sections():
    after = DOC.replace(">Audio<", ">Audio middleware<")
    v = verify_surgical(DOC, after, expected_sections=["At risk"])
    assert v.unchanged_count == len(chunk_map(DOC)) - 1


def test_sections_group_chunks_under_their_heading():
    named = {s.heading: s for s in sections(DOC)}
    assert set(named) == {"Digest", "What changed", "At risk", "Archive"}
    assert set(named["At risk"].chunk_ids) >= {"h2", "t1", "r1", "d1", "r2", "d2"}


def test_a_heading_wrapped_in_a_div_is_still_a_section():
    """bugs.md B12: the API answers 'add a section' with
    <div data-chunk-id><h2>New</h2><p>..</p></div>, so the heading has no chunk
    id of its own. It is a section to a reader, so it must be one here."""
    doc = (
        '<h1 data-chunk-id="h0">D</h1>'
        '<h2 data-chunk-id="h1">Traversal</h2><p data-chunk-id="p1">prose</p>'
        '<div data-chunk-id="dv"><h2>Grapple Rework</h2><p>spike</p></div>'
        '<h2 data-chunk-id="h2">Combat</h2><p data-chunk-id="p2">c</p>'
    )
    headings = [s.heading for s in sections(doc)]
    assert "Grapple Rework" in headings
    # and the wrapper belongs to the NEW section, not to the one before it
    by = {s.heading: s for s in sections(doc)}
    assert by["Grapple Rework"].chunk_ids == ["dv"]
    assert "dv" not in by["Traversal"].chunk_ids


def test_section_html_works_without_chunk_ids():
    """Exported HTML has no chunk ids (bugs.md B5). Degrade, do not return ''."""
    plain = "<h1>T</h1><h2>One</h2><p>a</p><h2>Two</h2><p>b</p>"
    assert "a</p>" in section_html(plain, "One")
    assert "b</p>" not in section_html(plain, "One")


def test_section_named_prefers_an_exact_match():
    doc = "<h2>Traversal</h2><p>x</p><h2>Traversal - Grapple Rework</h2><p>y</p>"
    assert section_named(doc, "Traversal").heading == "Traversal"


def test_table_rows_and_list_items_read_content():
    assert table_rows(section_html(DOC, "At risk")) == [["Audio"], ["Art"]]
    assert visible_text("<p>a <b>b</b></p>") == "a b"


@pytest.mark.skipif(not (REPRO / "B2-after-week-03-CORRUPTED.html").exists(),
                    reason="repro artefact not present")
def test_the_real_corrupted_document_is_detected():
    """The document the API actually returned when it destroyed a table.
    A diff against the good version must show the Archive section moving."""
    before = (REPRO / "B2-before-week-02.html").read_text(encoding="utf-8")
    after = (REPRO / "B2-after-week-03-CORRUPTED.html").read_text(encoding="utf-8")
    v = verify_surgical(before, after, expected_sections=["What changed"])
    assert not v.ok, "the corrupted document must not pass a surgical check"
    assert "<table" in before and "<table" not in section_html(after, "Archive")


def test_content_added_to_a_named_section_passes_but_a_duplicate_heading_does_not():
    """The line between "add to this section" and "add another section".

    Both shapes come back from the live API. Putting two images into the
    'Concept art' section produces chunks that cannot exist in the before
    document, so judging additions only against the before document called a
    correct edit unintended. Hanging the same images off a SECOND
    <h2>Concept art</h2> is bugs.md B15, and it must still fail.

    `allow_new=False` plus resolving the named section in BOTH documents
    separates them: content under the first heading of that name is intended,
    content under a second heading of the same name is not.
    """
    before = ('<h1>Art bible</h1><h2 data-chunk-id="h-p">Palette</h2>'
              '<p data-chunk-id="p1">warm</p>'
              '<h2 data-chunk-id="h-c">Concept art</h2><p data-chunk-id="c1">boards</p>')

    added_inside = before.replace('<p data-chunk-id="c1">boards</p>',
                                  '<p data-chunk-id="c1">boards</p>'
                                  '<div data-chunk-id="c2"><img src="a"><img src="b"></div>')
    v = verify_surgical(before, added_inside,
                        expected_sections=["Concept art"], allow_new=False)
    assert v.ok, f"images added inside the named section are the edit: {v.unintended}"

    duplicated = before + ('<h2 data-chunk-id="h-c2">Concept art</h2>'
                           '<div data-chunk-id="c3"><img src="a"></div>')
    v2 = verify_surgical(before, duplicated,
                         expected_sections=["Concept art"], allow_new=False)
    assert not v2.ok, "a second section with the same heading must not pass"
    assert set(v2.unintended) == {"h-c2", "c3"}


def test_text_diff_is_human_readable():
    d = text_diff("a\nb\nc", "a\nB\nc", label_a="w1", label_b="w2")
    assert "-b" in d and "+B" in d and "w1" in d
