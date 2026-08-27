"""Verification: proving the content landed, and never refusing correct work.

The headline test here is `test_verifier_accepts_whatever_the_renderer_emits`.
The sibling supplier-quality build shipped a verifier written against the one
example it was developed on, and the first run with a different document type
rejected a perfectly correct document. A verifier that wrongly refuses valid
work is worse than no verifier, so the renderer and the verifier are locked
together across every jurisdiction and every document kind.
"""
from __future__ import annotations

import zipfile

import pytest
from _builders import build_pack

from real_estate_pack.assemble import INDEX, LEASE, PACKET
from real_estate_pack.verify import document_was_modified, expected_facts, verify_export

STATES = ["US-CA", "US-TX", "US-NY", "US-FL"]
KINDS = [LEASE, PACKET, INDEX]


def write_rendered(tmp_path, doc_set, kind, suffix=".html"):
    path = tmp_path / f"{kind}{suffix}"
    path.write_text(doc_set.get(kind).content_html, encoding="utf-8")
    return str(path)


# --------------------------------------------------- the renderer/verifier pact


@pytest.mark.parametrize("code", STATES)
@pytest.mark.parametrize("kind", KINDS)
def test_verifier_accepts_whatever_the_renderer_emits(tmp_path, code, kind):
    """Whatever `render.py` produces must satisfy `verify.py`, for every
    jurisdiction and every document. This is the invariant that stops the
    verifier from ever again refusing valid work."""
    _, _, _, doc_set = build_pack(code)
    result = verify_export(write_rendered(tmp_path, doc_set, kind), doc_set, kind)
    assert result.ok, f"{code}/{kind} missing: {result.missing}"


@pytest.mark.parametrize("kind", KINDS)
def test_every_document_kind_has_facts_worth_checking(kind):
    _, _, _, doc_set = build_pack("US-CA")
    assert len(expected_facts(doc_set, kind)) >= 3


def test_an_unknown_document_kind_raises_rather_than_passing_vacuously():
    """An empty fact list would make verification trivially succeed."""
    _, _, _, doc_set = build_pack()
    with pytest.raises(ValueError, match="Unknown document kind"):
        expected_facts(doc_set, "not_a_document")


def test_expected_facts_are_deduplicated():
    """The same review date legitimately appears on many rules; reporting it
    missing five times helps nobody."""
    _, _, _, doc_set = build_pack("US-CA")
    facts = expected_facts(doc_set, INDEX)
    assert len(facts) == len(set(facts))


def test_index_facts_include_the_dates_that_make_the_pack_auditable():
    _, _, _, doc_set = build_pack("US-CA")
    facts = expected_facts(doc_set, INDEX)
    assert any(f.startswith("2025-") for f in facts)
    assert any(f.startswith("202") and f.count("-") == 2 for f in facts)


def test_packet_facts_include_statutory_anchors():
    _, _, _, doc_set = build_pack("US-FL")
    facts = expected_facts(doc_set, PACKET)
    assert any("RADON GAS" in f for f in facts)


# ------------------------------------------------------------- catching faults


def test_a_missing_disclosure_is_detected(tmp_path):
    _, _, _, doc_set = build_pack("US-FL")
    dropped = doc_set.disclosure_ids()[-1]
    path = tmp_path / "packet.html"
    path.write_text(doc_set.get(PACKET).content_html.replace(dropped, "ZZ"), encoding="utf-8")
    result = verify_export(str(path), doc_set, PACKET)
    assert not result.ok
    assert dropped in result.missing


def test_reworded_statutory_text_is_detected(tmp_path):
    """The defect that reads perfectly well and is still non-compliant."""
    _, _, _, doc_set = build_pack("US-FL")
    path = tmp_path / "packet.html"
    path.write_text(
        doc_set.get(PACKET).content_html.replace(
            "Radon is a naturally occurring radioactive gas", "Radon is a natural radioactive gas"
        ),
        encoding="utf-8",
    )
    result = verify_export(str(path), doc_set, PACKET)
    assert not result.ok


def test_an_empty_export_fails_rather_than_passing(tmp_path):
    _, _, _, doc_set = build_pack()
    path = tmp_path / "empty.html"
    path.write_text("", encoding="utf-8")
    result = verify_export(str(path), doc_set, LEASE)
    assert not result.ok
    assert len(result.missing) == result.checked


def test_html_entities_do_not_cause_a_false_failure(tmp_path):
    """A fact containing `&` survives a round trip as `&amp;` and must still
    match."""
    _, _, _, doc_set = build_pack(landlord_name="Smith & Sons")
    result = verify_export(write_rendered(tmp_path, doc_set, LEASE), doc_set, LEASE)
    assert result.ok, result.missing


def test_markup_between_paragraphs_does_not_cause_a_false_failure(tmp_path):
    """Regression, and the reason the invariant test above exists.

    The renderer splits a notice on blank lines into `</p><p>`. Before the
    extractor stripped tags, that markup sat in the middle of every statutory
    passage and no anchor matched — so the verifier rejected its own renderer's
    correct output for all four jurisdictions at once."""
    _, _, _, doc_set = build_pack("US-FL")
    packet = doc_set.get(PACKET).content_html
    assert "</p><p>" in packet, "precondition: the renderer really does split paragraphs"
    assert verify_export(write_rendered(tmp_path, doc_set, PACKET), doc_set, PACKET).ok


def test_a_word_split_across_docx_runs_still_matches(tmp_path):
    """Word legitimately splits a single word across runs. Whitespace-insensitive
    comparison is what makes that survivable."""
    _, _, _, doc_set = build_pack("US-TX")
    path = tmp_path / "lease.docx"
    body = "".join(
        "".join(f"<w:t>{ch}</w:t>" for ch in str(f)) for f in expected_facts(doc_set, LEASE)
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    assert verify_export(str(path), doc_set, LEASE).ok


def test_reflowed_whitespace_does_not_cause_a_false_failure(tmp_path):
    """A template legitimately reflows text. Only wording changes should fail."""
    _, _, _, doc_set = build_pack("US-FL")
    path = tmp_path / "packet.html"
    reflowed = doc_set.get(PACKET).content_html.replace("<br />", "\n     \n")
    path.write_text(reflowed, encoding="utf-8")
    assert verify_export(str(path), doc_set, PACKET).ok


# ------------------------------------------------------------- format handling


def test_a_docx_export_is_read_back_without_a_docx_dependency(tmp_path):
    """A .docx is a zip; its body XML is checked directly."""
    _, _, _, doc_set = build_pack("US-TX")
    path = tmp_path / "lease.docx"
    body = "".join(f"<w:t>{f}</w:t>" for f in expected_facts(doc_set, LEASE))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    assert verify_export(str(path), doc_set, LEASE).ok


def test_a_corrupt_docx_is_reported_as_unreadable_not_as_a_pass(tmp_path):
    _, _, _, doc_set = build_pack()
    path = tmp_path / "broken.docx"
    path.write_bytes(b"this is not a zip file")
    result = verify_export(str(path), doc_set, LEASE)
    assert not result.readable
    assert not result.ok
    assert "could not read" in result.note


def test_an_unverifiable_format_is_reported_as_skipped_never_as_passed(tmp_path):
    """PDF text extraction is out of scope. Saying so is honest; counting it as
    a pass would not be."""
    _, _, _, doc_set = build_pack()
    path = tmp_path / "lease.pdf"
    path.write_bytes(b"%PDF-1.4")
    result = verify_export(str(path), doc_set, LEASE)
    assert not result.readable
    assert "verification skipped, not passed" in result.note
    assert not result.ok, "an unverified export must never report ok"


# ------------------------------------------------- 'completed' is not 'applied'


def test_a_turn_that_returned_no_html_did_not_modify_anything():
    assert document_was_modified({}, "<p>original</p>") is False
    assert document_was_modified({"document_changes": {}}, "<p>original</p>") is False
    assert document_was_modified({"document_changes": {"updated_html": ""}}, "<p>x</p>") is False


def test_html_identical_to_what_was_uploaded_is_not_a_modification():
    """The live failure the sibling build hit: a completed job whose every
    operation failed, leaving the document untouched."""
    original = "<p>original</p>"
    assert document_was_modified({"document_changes": {"updated_html": original}}, original) is False
    assert document_was_modified({"document_changes": {"updated_html": f"  {original}  "}}, original) is False


def test_genuinely_changed_html_is_a_modification():
    assert document_was_modified({"document_changes": {"updated_html": "<p>new</p>"}}, "<p>old</p>") is True
