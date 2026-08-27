"""The measured corpus, and the numbers nothing else is holding.

`RECOVERY.md` and the README quote figures. A figure in prose is a claim nobody
is checking, so these tests re-run the corpus and fail if the committed
measurements and the code disagree — which is the same guard the interface
fixtures already have, pointed at a number instead of a payload.

The bars themselves are in `measure.ACCEPTABLE`, written down before the run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docrepair import corpus, measure

MEASUREMENTS = Path(__file__).resolve().parents[1] / "corpus" / "measurements.json"


@pytest.fixture(scope="module")
def measured() -> dict:
    return measure.run()


def test_the_committed_measurements_are_what_the_code_produces_today(measured):
    """The published numbers, re-derived. Regenerate with `-m docrepair.measure --write`."""
    committed = json.loads(MEASUREMENTS.read_text())
    assert committed["summary"] == measured["summary"], (
        "corpus/measurements.json no longer matches a fresh run. Re-run "
        "`python3 -m docrepair.measure --write`, read the diff, and correct "
        "RECOVERY.md and the README before committing it."
    )


def test_damage_that_destroys_nothing_gives_every_word_back(measured):
    """The one bar with no excuse behind it.

    Every one of these fixtures still holds all of the owner's words somewhere
    in its bytes. A partial recovery here is not the damage's fault.
    """
    short = [r for r in measured["fixtures"]
             if r["kind"] == corpus.LOSSLESS and r["verdict"] != measure.FULL]
    assert not short, [
        (r["fixture"], r["verdict"], r["word_recall"]) for r in short]


def test_no_fixture_comes_back_as_an_empty_success(measured):
    """The output this build exists to prevent: a file that opens with nothing in it."""
    empty = [r["fixture"] for r in measured["fixtures"]
             if r["verdict"] == measure.EMPTY_SUCCESS]
    assert not empty, empty


def test_nothing_in_the_corpus_makes_the_repair_raise(measured):
    """A crash is worse than a refusal — it reaches the page as a 500 with no
    explanation, and the owner learns nothing about their document."""
    crashed = [(r["fixture"], r.get("error")) for r in measured["fixtures"]
               if r["verdict"] == measure.CRASHED]
    assert not crashed, crashed


def test_every_verdict_is_inside_what_its_damage_kind_allows(measured):
    assert measured["summary"]["unexpected"] == []


def test_the_yardstick_does_not_read_table_markup_as_text():
    """`<w:t[^>]*>` also matches `<w:tbl>`, and then swallows the table.

    This is here because both this module's ground truth and the engine's
    last-resort text extraction had that exact bug, and the second one put raw
    XML into a recovered document.
    """
    doc = corpus._report()
    text = corpus.text_of(doc)
    assert "Region" in text and "EMEA" in text
    for markup in ("w:tblPr", "w:tcW", "tblStyle", "<w:"):
        assert markup not in text


def test_the_yardstick_does_not_split_a_word_across_two_runs():
    """Word starts a new run mid-word whenever formatting changes, so runs
    inside a paragraph join with nothing between them."""
    body = (b'<?xml version="1.0"?><w:document xmlns:w="x"><w:body><w:p>'
            b"<w:r><w:t>adi</w:t></w:r><w:r><w:t>piscing</w:t></w:r></w:p>"
            b"<w:p><w:r><w:t>elit</w:t></w:r></w:p></w:body></w:document>")
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", body)
    text = corpus.text_of(buf.getvalue())
    assert "adipiscing" in text
    assert "adi piscing" not in text
    assert "elit" in text and "adipiscingelit" not in text


def test_the_corpus_covers_documents_this_package_did_not_write():
    """A repair tool measured only against its own output is measured against
    its own assumptions."""
    others = {b.written_by for b in corpus.BASES} - {"this package"}
    assert len(others) >= 3, others


def test_every_damage_mode_is_applied_to_every_document_that_can_take_it():
    built = corpus.build()
    with_media = [b for b in corpus.BASES
                  if corpus.counts_of(b.bytes())["images"] > 0]
    media_modes = [d for d in corpus.DAMAGES if d.needs_media]
    expected = (len(corpus.BASES) * (len(corpus.DAMAGES) - len(media_modes))
                + len(with_media) * len(media_modes))
    assert len(built) == expected
