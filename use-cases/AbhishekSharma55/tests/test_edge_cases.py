"""Edge cases found by attacking the kit on purpose, after it was working.

Written as a fresh adversarial pass rather than alongside the code, because a
test written by the person who just wrote the function tends to test what the
function does rather than what it must never do.
"""

from superdocs_kit.docdiff import (
    chunk_map,
    diff_chunks,
    residue_map,
    section_html,
    sections,
    verify_surgical,
    visible_text,
)

DOC = '<h2 data-chunk-id="h">S</h2><p data-chunk-id="p">t</p>'


def test_an_empty_document_does_not_crash_anything():
    assert sections("") == []
    assert chunk_map("") == {}
    assert verify_surgical("", "", expected_sections=["anything"]).ok


def test_malformed_html_degrades_instead_of_exploding():
    """Unclosed tags happen. A parser that raises here takes the run down."""
    bad = ('<h2 data-chunk-id="a">A</h2><p data-chunk-id="b">unclosed'
           '<div data-chunk-id="c">x')
    assert "a" in chunk_map(bad)


def test_identical_documents_report_no_change_at_all():
    d = diff_chunks(DOC, DOC)
    assert d.modified == [] and d.added == [] and d.removed == []
    assert len(d.unchanged) == 2


def test_a_deleted_section_is_detected_not_ignored():
    d = diff_chunks(DOC, '<h2 data-chunk-id="h">S</h2>')
    assert d.removed == ["p"]


def test_nbsp_is_a_byte_change_but_not_a_text_change():
    """Both halves matter. The byte diff must see it, or a formatting-only
    rewrite goes unnoticed. The text comparison must NOT, or a status line the
    model got exactly right fails its fidelity check - which is the bug that
    cost me four weeks of a run."""
    a = '<p data-chunk-id="p">Week 6</p>'
    b = '<p data-chunk-id="p">Week&nbsp;6</p>'
    assert diff_chunks(a, b).modified == ["p"]
    assert visible_text(a) == visible_text(b)


def test_a_leaf_chunks_residue_is_its_own_html():
    assert residue_map(DOC)["p"] == '<p data-chunk-id="p">t</p>'


def test_an_edit_under_an_unnamed_section_is_unintended():
    """The failure mode that matters: naming a section that does not exist must
    not make the check vacuously pass."""
    v = verify_surgical(DOC, DOC.replace(">t<", ">u<"), expected_sections=["Nonexistent"])
    assert not v.ok and v.unintended == ["p"]


def test_section_slice_stops_at_the_next_heading():
    plain = "<h1>T</h1><h2>A</h2><p>x</p><h2>B</h2><p>y</p>"
    assert "x" in section_html(plain, "A")
    assert "y" not in section_html(plain, "A")


def test_a_document_that_lost_all_its_content_is_not_reported_as_clean():
    v = verify_surgical(DOC, "", expected_sections=["S"])
    assert v.detail["removed"] == ["h", "p"]
