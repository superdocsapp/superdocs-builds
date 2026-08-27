"""Whether the rebuilt package is one Word will actually open.

There is no Word on the build machine, so this asserts the structural
invariants Word enforces when it decides a file is corrupt. Every one of them
was broken by a real defect in this package's own writer:

  * a part with no declared content type (an image extension the writer did not
    recognise but wrote anyway),
  * a relationship part that is not well-formed XML (a member name carrying a
    quote, interpolated raw),
  * a drawing whose `r:embed` names a relationship that does not exist (a
    picture refused by the writer but still referenced by the body).

Each produced a *repaired* file that would not open, handed to somebody whose
entire complaint was that their file would not open.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from tests import broken, fixtures

from docrepair import engine

PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def assert_valid_docx(blob: bytes) -> None:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()

        # 1. The parts Word requires, present and parseable.
        for required in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
            assert required in names, f"missing {required}"
        types = ET.fromstring(z.read("[Content_Types].xml"))
        document = ET.fromstring(z.read("word/document.xml"))

        # 2. Every extension in the package is declared.
        defaults = {el.get("Extension", "").lower()
                    for el in types.findall(f"{CT}Default")}
        overrides = {el.get("PartName", "") for el in types.findall(f"{CT}Override")}
        for name in names:
            if "/" + name in overrides:
                continue
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            assert ext in defaults, f"{name}: extension {ext!r} is not declared"

        # 3. The relationship parts are well-formed, and their targets exist.
        rels_part = "word/_rels/document.xml.rels"
        rel_targets: dict[str, str] = {}
        if rels_part in names:
            for rel in ET.fromstring(z.read(rels_part)):
                rid, target = rel.get("Id"), rel.get("Target")
                assert rid and target, "a relationship with no id or no target"
                rel_targets[rid] = target
                if rel.get("TargetMode") == "External":
                    continue
                assert f"word/{target}" in names, f"{rid} points at nothing: {target}"

        # 4. Every picture the body asks for has a relationship to ask through.
        for blip in document.iter(f"{A_NS}blip"):
            rid = blip.get(f"{R_NS}embed") or blip.get(f"{R_NS}link")
            if rid:
                assert rid in rel_targets, f"drawing references {rid}, which is not declared"

        # 5. No member escapes its folder.
        for name in names:
            assert ".." not in name and not name.startswith("/"), name


@pytest.mark.parametrize("maker", [
    broken.healthy,
    broken.truncated_container,
    broken.missing_content_types,
    broken.unclosed_tags,
    fixtures.illustrated,
])
def test_the_rebuilt_package_is_structurally_valid(maker):
    r = engine.repair(maker(), "b.docx")

    assert r.ok
    assert_valid_docx(r.output)


def test_the_package_stays_valid_when_a_picture_had_to_be_refused():
    """The case that used to produce the broken file: the writer dropped the
    picture and the body kept pointing at it."""
    whole = fixtures.png()
    src = fixtures.package(
        body=f'<w:p>{fixtures.drawing("rId2")}<w:r><w:t>Report</w:t></w:r></w:p>',
        rels=fixtures.rels({"rId2": "media/cut.png"}),
        media_parts={"word/media/cut.png": whole[:len(whole) // 2]},
    )

    r = engine.repair(src, "cut.docx")

    assert r.ok
    assert_valid_docx(r.output)
    assert fixtures.media_names(r.output) == []


def test_the_package_stays_valid_across_the_whole_damaged_corpus():
    """The broadest sweep available: every fixture the corpus builds, every one
    that came back with a file, checked for the invariants Word enforces."""
    from docrepair import corpus

    checked = 0
    for fixture in corpus.build():
        result = engine.repair(fixture.data, filename=f"{fixture.name}.docx")
        if not result.output:
            continue
        assert_valid_docx(result.output)
        checked += 1

    assert checked > 50, f"only {checked} fixtures produced a file; expected most of 87"
