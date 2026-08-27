"""The recovery floor: what it gives back, and what it refuses to claim.

Written against the `Result` the engine actually produces. The suite this
replaces was written against a different shape (`Repair`, with `.recovered`,
`.counts` and `.stages`) and was deleted rather than adapted when the engine was
rewritten; these are the behaviours from it that still have an owner, plus the
ones the picture work added.
"""

from __future__ import annotations

import zipfile
import io

import pytest

from tests import broken, fixtures

from docrepair import engine


def _opens(blob: bytes) -> bool:
    """The only question that matters about the output."""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return z.read("word/document.xml").startswith(b"<?xml")
    except Exception:  # noqa: BLE001
        return False


# -- the floor holds ---------------------------------------------------------

@pytest.mark.parametrize("maker", [
    broken.healthy,
    broken.truncated_container,
    broken.missing_content_types,
    broken.unclosed_tags,
])
def test_a_damaged_document_comes_back_as_a_file_that_opens(maker):
    r = engine.repair(maker(), "broken.docx")

    assert r.ok, f"{maker.__name__} returned nothing"
    assert _opens(r.output), f"{maker.__name__} produced a file that will not open"
    assert r.word_count > 0


def test_the_verdict_is_one_of_the_three_honest_tokens():
    for maker in (broken.healthy, broken.truncated_container, broken.unclosed_tags):
        assert engine.repair(maker(), "b.docx").verdict in {"full", "partial", "refused"}


def test_nothing_is_claimed_when_there_is_nothing_to_claim():
    """A file with no document part is refused, and refused says so."""
    r = engine.repair(b"not a zip at all, just bytes", "junk.docx")

    assert not r.ok
    assert r.verdict == "refused"
    assert r.output == b""
    assert r.lost, "a refusal with no reason is not a refusal"


def test_a_refusal_does_not_offer_a_download():
    r = engine.repair(b"", "empty.docx")

    assert not r.ok
    assert r.images_recovered == 0
    assert r.preview_html == ""


# -- structure ---------------------------------------------------------------

def test_headings_and_tables_survive_a_readable_document():
    r = engine.repair(fixtures.illustrated(), "site.docx")

    assert r.structure_preserved
    assert r.method == "xml"
    assert r.tables_recovered == 1
    assert r.headings_recovered >= 1


def test_a_body_too_damaged_to_parse_still_gives_the_words_back():
    """The floor beneath the floor. Structure is gone and the report says so —
    it is not quietly presented as a recovered document."""
    r = engine.repair(broken.unclosed_tags(), "b.docx")

    assert r.ok and r.word_count > 0
    if not r.structure_preserved:
        assert r.method == "regex"
        assert any("structure" in note for note in r.lost)


# -- the engine does not need the network, a key, or a heavy dependency ------

def test_the_floor_imports_without_lxml_or_python_docx():
    """Both were declared dependencies and neither was installed, so the engine
    could not import at all in a fresh checkout. The recovery floor is stdlib;
    `lxml` is used when present and its absence costs one tier of tolerance."""
    import ast
    import pathlib

    source = (pathlib.Path(engine.__file__)).read_text()
    tree = ast.parse(source)
    top_level = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top_level.add(node.module.split(".")[0])

    assert "lxml" not in top_level
    assert "docx" not in top_level, "python-docx at module scope, and it shadows docrepair.docx"
