"""The pictures, which are the part people lose.

Every test here is a flaw that shipped. The headline one — BUG-085 — is that the
live engine had been replaced with a text-only rebuild that never looked at
`word/media/` at all, so a repaired file lost every image on every document
while still reporting the verdict "full". The rest are defects in the picture
code that regression was hiding, two of which produced a *repaired* file that
Word itself refuses to open.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

from tests import fixtures
import pytest

from docrepair import docx, engine, media
from docrepair.docx import Block


# -- F1: the engine reads media at all ---------------------------------------

def test_a_repaired_document_still_has_its_picture():
    """BUG-085. The whole complaint, as one assertion."""
    src = fixtures.illustrated()
    r = engine.repair(src, "site.docx")

    assert r.ok
    assert r.images_recovered == 1
    assert fixtures.media_names(r.output) == ["word/media/image1.png"]


def test_the_recovered_picture_is_the_original_bytes():
    """Not re-encoded, not resized. The owner's file, carried across."""
    src = fixtures.illustrated()
    r = engine.repair(src, "site.docx")

    assert fixtures.part(r.output, "word/media/image1.png") == fixtures.png()


def test_the_picture_survives_the_damage_that_destroys_the_index():
    """A picture is its own ZIP member, so it outlives the central directory —
    which is exactly the damage Word reports as a corrupt file."""
    src = fixtures.illustrated()
    zeroed_eocd = src[:-22] + b"\x00" * 22

    r = engine.repair(zeroed_eocd, "site.docx")

    assert r.images_recovered == 1
    assert fixtures.part(r.output, "word/media/image1.png") == fixtures.png()


def test_the_preview_shows_the_picture():
    """The preview answers "was any of this worth it", which it cannot do with
    the pictures left out of it."""
    r = engine.repair(fixtures.illustrated(), "site.docx")

    assert 'src="data:image/png;base64,' in r.preview_html


# -- F2: images the old walker could not see ---------------------------------

def test_a_picture_inside_a_content_control_is_recovered():
    """`<w:sdt>` wraps content in Google Docs exports and every Word template.
    A walker that reads only the direct children of the body skipped the wrapper
    whole — its text and its pictures with it."""
    src = fixtures.package(
        body=('<w:sdt><w:sdtContent>'
              f'<w:p>{fixtures.drawing("rId2")}<w:r><w:t>Wrapped</w:t></w:r></w:p>'
              '</w:sdtContent></w:sdt>'),
        rels=fixtures.rels({"rId2": "media/sdt.png"}),
        media_parts={"word/media/sdt.png": fixtures.png()},
    )

    r = engine.repair(src, "sdt.docx")

    assert r.images_recovered == 1
    assert r.images_unplaced == 0, "it was placeable; it should not be at the end"
    assert "Wrapped" in fixtures.part(r.output, "word/document.xml").decode()


def test_a_picture_inside_a_table_cell_is_recovered_and_the_move_is_stated():
    """The cell reader took text and nothing else, so a photograph in a cell was
    never seen as placed. It is recovered and set after the table — and the
    report says so, because a reader who sees it leave the grid is owed why."""
    src = fixtures.package(
        body=('<w:tbl><w:tr>'
              '<w:tc><w:p><w:r><w:t>Cell A</w:t></w:r></w:p></w:tc>'
              f'<w:tc><w:p>{fixtures.drawing("rId2")}</w:p></w:tc>'
              '</w:tr></w:tbl>'),
        rels=fixtures.rels({"rId2": "media/cell.png"}),
        media_parts={"word/media/cell.png": fixtures.png()},
    )

    r = engine.repair(src, "cell.docx")

    assert r.images_recovered == 1
    assert r.tables_recovered == 1
    assert any("inside a table" in note for note in r.lost)


# -- F3: a package Word will actually open -----------------------------------

def test_a_picture_format_we_cannot_declare_is_refused_rather_than_shipped():
    """`[Content_Types].xml` must declare every extension in the package. It used
    to declare only the ones it recognised while the writer wrote the part
    regardless — so an HD Photo produced a rebuild Word calls corrupt. Handing
    somebody a second unopenable file is worse than one picture missing."""
    unknown = media.Image(name="word/media/x.wdp", data=b"WDPHOTO\x00" * 40,
                          width_px=1, height_px=1, measured=False, complete=True)
    blocks = [Block("paragraph", "text"), Block("image", text=unknown.name,
                                                image=unknown)]

    plan = docx.plan_media(blocks)
    out = docx.write_docx(blocks, plan)

    assert plan.carried == {}
    assert [d.image.name for d in plan.dropped] == ["word/media/x.wdp"]
    assert fixtures.media_names(out) == []
    _assert_every_part_is_declared(out)


def test_the_extension_comes_from_the_bytes_not_the_name():
    """A JPEG called `.png` is written by more tools than it should be, and
    declaring the wrong type is the same broken package by another route."""
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
    lying = media.Image(name="word/media/actually-a-jpeg.png", data=jpeg,
                        width_px=8, height_px=6, measured=False, complete=True)

    out = docx.write_docx([Block("image", text=lying.name, image=lying)])

    assert fixtures.media_names(out) == ["word/media/image1.jpg"]
    _assert_every_part_is_declared(out)


def _assert_every_part_is_declared(blob: bytes) -> None:
    """No part may have an extension the content types part does not name."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        declared = {
            el.get("Extension", "").lower()
            for el in ET.fromstring(z.read("[Content_Types].xml"))
            if el.tag.endswith("Default")
        }
        for name in z.namelist():
            ext = name.rsplit(".", 1)[-1].lower()
            assert ext in declared, f"{name} has no declared content type"


# -- F4: names out of the damaged file are not trusted -----------------------

@pytest.mark.parametrize("hostile", [
    'word/media/a"b.png',
    "word/media/<script>.png",
    "word/media/x&y.png",
])
def test_a_hostile_member_name_still_produces_a_file_that_opens(hostile):
    """The name comes out of an archive somebody else controls. One quote in it
    used to leave the relationship part malformed — a rebuild that does not
    open, handed to somebody whose complaint was that their file does not open."""
    img = fixtures.picture(name=hostile)

    out = docx.write_docx([Block("image", text=img.name, image=img)])

    with zipfile.ZipFile(io.BytesIO(out)) as z:
        ET.fromstring(z.read("word/_rels/document.xml.rels"))
        ET.fromstring(z.read("word/document.xml"))


def test_a_member_name_cannot_walk_out_of_the_media_folder():
    """`startswith("word/media/")` passes `word/media/../../evil`, and the name
    went straight to `writestr`. Names are reissued, so it cannot."""
    img = fixtures.picture(name="word/media/../../../evil.png")

    out = docx.write_docx([Block("image", text=img.name, image=img)])

    assert fixtures.media_names(out) == ["word/media/image1.png"]
    with zipfile.ZipFile(io.BytesIO(out)) as z:
        assert all(".." not in n for n in z.namelist())


# -- F5: half a picture is not a picture -------------------------------------

def test_a_picture_cut_short_by_the_damage_is_not_embedded():
    """`salvage` keeps the prefix of a broken stream, which is right for a body
    and wrong for an image: half a PNG is not half a photograph, it is a grey
    box. It is refused, and the refusal is reported."""
    whole = fixtures.png()
    img = fixtures.picture(name="word/media/cut.png", data=whole[:len(whole) // 2])
    blocks = [Block("image", text=img.name, image=img)]

    assert img.complete is False
    plan = docx.plan_media(blocks)

    assert plan.carried == {}
    assert "cut short" in plan.dropped[0].reason
    assert fixtures.media_names(docx.write_docx(blocks, plan)) == []


def test_an_intact_picture_is_not_mistaken_for_a_truncated_one():
    """The other half of the check. A guard that refuses good pictures would
    cause the very loss it exists to prevent."""
    assert media.is_complete(fixtures.png()) is True
    assert media.is_complete(b"\xff\xd8\xff\xe0" + b"\x00" * 8 + b"\xff\xd9") is True


# -- the verdict tells the truth about pictures ------------------------------

def test_a_picture_destroyed_by_the_damage_is_reported_and_costs_the_verdict():
    """The loss nothing else can see: an image the damage destroyed never
    reaches `media.collect`, so the writer has nothing to refuse. The surviving
    reference in the body is the evidence it was ever there."""
    src = fixtures.illustrated()
    r = engine.repair(src[:int(len(src) * 0.6)], "site.docx")

    assert r.ok
    assert r.verdict == "partial", "a document that lost a photograph is not full"
    assert any("destroyed by the damage" in note for note in r.images_lost)


def test_a_document_that_kept_everything_is_full():
    """The bar has to be reachable, or it is not a bar."""
    r = engine.repair(fixtures.illustrated(), "site.docx")

    assert r.verdict == "full"
    assert r.images_lost == []


# -- F7 / F8: saying the true thing about a picture --------------------------

def test_a_linked_picture_is_not_reported_as_lost_from_the_file():
    """It was never in the file. "We could not recover this" would be telling
    somebody the damage cost them something it did not."""
    src = fixtures.package(
        body=f'<w:p>{fixtures.drawing("rId2")}<w:r><w:t>Hello</w:t></w:r></w:p>',
        rels=fixtures.rels({"rId2": "https://example.invalid/logo.png"},
                           external={"rId2"}),
        media_parts={},
    )

    r = engine.repair(src, "linked.docx")

    assert any("linked from somewhere else" in note for note in r.images_lost)
    assert not any("destroyed by the damage" in note for note in r.images_lost)


def test_a_header_picture_is_named_as_a_header_picture():
    """Its relationship lives in the header's own rels part, so it cannot be
    placed in the body — but "this was in the page header" is a true sentence
    and "we do not know where this went" is not."""
    src = fixtures.package(
        body="<w:p><w:r><w:t>Body text</w:t></w:r></w:p>",
        rels=fixtures.rels({}),
        media_parts={"word/media/logo.png": fixtures.png()},
    )
    with zipfile.ZipFile(io.BytesIO(src)) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    parts["word/_rels/header1.xml.rels"] = fixtures.rels({"rId1": "media/logo.png"})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, blob in parts.items():
            z.writestr(name, blob)

    r = engine.repair(buf.getvalue(), "header.docx")

    assert r.images_recovered == 1
    assert r.images_unplaced == 1
    assert "the page header" in fixtures.part(
        r.output, "word/document.xml").decode()


def test_an_unplaceable_picture_is_kept_under_a_heading_that_says_so():
    """Returned rather than dropped, and obviously placed rather than silently
    placed wrong."""
    src = fixtures.package(
        body="<w:p><w:r><w:t>Body text</w:t></w:r></w:p>",
        rels=fixtures.rels({}),
        media_parts={"word/media/orphan.png": fixtures.png()},
    )

    r = engine.repair(src, "orphan.docx")

    assert r.images_recovered == 1
    assert r.images_unplaced == 1
    assert engine.PICTURES_HEADING in fixtures.part(
        r.output, "word/document.xml").decode()


# -- F4, at the level the escaping actually lives ----------------------------
#
# The tests above pass because names are reissued before they ever reach the
# writers, which is the primary fix. Escaping is the second line: these two
# functions are public and take a name from their caller, so they must be safe
# on their own terms rather than only safe because of what currently calls them.
# A mutation run caught this — removing `esc_attr` left every test above green.

def test_drawing_markup_is_well_formed_for_a_hostile_name():
    img = fixtures.picture()

    xml = media.drawing_xml("rId2", img, 1, 'a"b<c&d')

    ET.fromstring(
        '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        + xml.split("<w:p>", 1)[1]
    )


def test_relationship_markup_is_well_formed_for_a_hostile_target():
    rels = docx.doc_rels([("rId2", 'media/a"b<c&d.png')])

    parsed = ET.fromstring(rels)
    targets = [el.get("Target") for el in parsed]

    assert 'media/a"b<c&d.png' in targets, "escaped on the way in, intact on the way out"
