"""Read structure out of a damaged document part, and write a valid one back.

The writer matters as much as the reader. A tool that salvages text and hands
back a .txt has not repaired anything -- the owner wanted a Word file. So this
builds a real DOCX: a correct `[Content_Types].xml`, the two relationship
parts, a stylesheet with actual heading styles, and a document body.

The output is deliberately plain. Recovering someone's original theme is not
possible from a broken file, and pretending otherwise would be the "silent
claim of a full fix" the brief warns against. What it guarantees is a file that
opens, with headings that are headings and tables that are tables.
"""

from __future__ import annotations

import base64
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from . import media
from .media import Image
from .salvage import W

def content_types(extensions: list[str] | None = None) -> str:
    """Word will not open a package whose parts have no declared type, so an
    image extension carried into the rebuild has to be declared here as well as
    written into the archive. Missing this produces a file that opens on some
    machines and is called corrupt on others, which is the worst of the three
    possible outcomes."""
    defaults = "".join(
        f'<Default Extension="{e}" ContentType="{media.CONTENT_TYPES[e]}"/>'
        for e in sorted(set(extensions or [])) if e in media.CONTENT_TYPES
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + defaults +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )


CONTENT_TYPES = content_types()

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

IMAGE_REL = ("http://schemas.openxmlformats.org/officeDocument/2006/"
             "relationships/image")


def doc_rels(images: list[tuple[str, str]] | None = None) -> str:
    """`rId1` is always the stylesheet; images take rId2 upwards.

    Targets are escaped: they derive from member names read out of the damaged
    original, and one quote in one of them used to produce a rebuild whose
    relationship part was malformed — a file that does not open, handed to
    somebody whose complaint was that their file does not open.
    """
    extra = "".join(
        f'<Relationship Id="{rid}" Type="{IMAGE_REL}" '
        f'Target="{media.esc_attr(target)}"/>'
        for rid, target in (images or [])
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        + extra + "</Relationships>"
    )


DOC_RELS = doc_rels()


def _style(sid: str, name: str, size: int, bold: bool, outline: int | None) -> str:
    outline_xml = f'<w:outlineLvl w:val="{outline}"/>' if outline is not None else ""
    return (
        f'<w:style w:type="paragraph" w:styleId="{sid}">'
        f'<w:name w:val="{name}"/><w:qFormat/>'
        f'<w:pPr><w:spacing w:before="240" w:after="120"/>{outline_xml}</w:pPr>'
        f'<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>'
        f'<w:sz w:val="{size}"/>{"<w:b/>" if bold else ""}</w:rPr></w:style>'
    )


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/>'
    '</w:rPr></w:rPrDefault></w:docDefaults>'
    + _style("Normal", "Normal", 22, False, None)
    + _style("Title", "Title", 56, True, 0)
    + _style("Heading1", "heading 1", 32, True, 0)
    + _style("Heading2", "heading 2", 26, True, 1)
    + _style("Heading3", "heading 3", 24, True, 2)
    + "</w:styles>"
)


@dataclass
class Block:
    kind: str          # "heading" | "paragraph" | "table" | "image"
    text: str = ""
    level: int = 1
    rows: list[list[str]] | None = None
    image: Image | None = None
    #: Set when the picture was found inside a table cell and so is written
    #: after the table rather than in it. The report says so; a reader who sees
    #: a photograph move out of a cell should be told why.
    from_table: bool = False


def read_blocks(document_xml: bytes, targets: dict[str, str] | None = None,
                images: dict[str, Image] | None = None) -> list[Block]:
    """Parse the body into blocks, keeping the structure that survived.

    `targets` and `images` are what makes a picture land back where it was: the
    relationship map says which file a drawing points at, and without it a
    drawing is a reference to nothing. Both optional, because both parts can be
    damaged, and a document with unplaceable images is still a document.
    """
    targets = targets or {}
    images = images or {}
    root = ET.fromstring(document_xml)
    body = root.find(f"{W}body")
    if body is None:
        return []

    blocks: list[Block] = []
    _walk(body, targets, images, blocks)
    return blocks


def _walk(container: ET.Element, targets: dict[str, str],
          images: dict[str, Image], blocks: list[Block]) -> None:
    """Collect blocks from a body-like container, following the wrappers.

    Iterating the direct children of `<w:body>` and stopping there misses two
    things that are ordinary rather than exotic:

    * `<w:sdt>` — a content control. Google Docs and every Word template built
      on one of these wrap whole paragraphs and tables in them, and a walker
      that does not step inside sees an empty document where a person sees
      their text.
    * a picture inside a table cell. The cell reader takes text and nothing
      else, so the image was never counted as placed and fell through to the
      end of the document — if it survived at all.
    """
    for el in container:
        if el.tag == f"{W}sdt":
            # The control is a wrapper; its content is the document's content.
            content = el.find(f"{W}sdtContent")
            if content is not None:
                _walk(content, targets, images, blocks)
        elif el.tag == f"{W}p":
            for img in _images_in(el, targets, images):
                blocks.append(Block("image", text=img.name, image=img))
            text = _para_text(el)
            if not text.strip():
                continue
            level = _heading_level(el)
            blocks.append(
                Block("heading", text, level) if level else Block("paragraph", text)
            )
        elif el.tag == f"{W}tbl":
            rows = []
            for tr in el.iter(f"{W}tr"):
                rows.append([_cell_text(tc) for tc in tr.findall(f"{W}tc")])
            if rows:
                blocks.append(Block("table", rows=rows))
            # A cell's pictures follow the table rather than being written back
            # into it. `_table` writes text-only cells, and inventing drawing
            # markup inside one to hold an image would be this module guessing
            # at a layout it did not read. The rule the package already states
            # applies here too: obviously placed beats silently placed wrong.
            for img in _images_in(el, targets, images):
                blocks.append(Block("image", text=img.name, image=img,
                                    from_table=True))


def _images_in(el: ET.Element, targets: dict[str, str],
               images: dict[str, Image]) -> list[Image]:
    """The pictures this element references, in the order it references them."""
    out: list[Image] = []
    for rid in media.embedded_ids(el):
        img = images.get(targets.get(rid, ""))
        if img is not None:
            out.append(img)
    return out


def _para_text(p: ET.Element) -> str:
    return "".join(t.text or "" for t in p.iter(f"{W}t"))


def _cell_text(tc: ET.Element) -> str:
    return " ".join(_para_text(p) for p in tc.findall(f"{W}p")).strip()


def _heading_level(p: ET.Element) -> int | None:
    ppr = p.find(f"{W}pPr")
    if ppr is None:
        return None
    style = ppr.find(f"{W}pStyle")
    if style is None:
        return None
    val = style.get(f"{W}val", "")
    m = re.fullmatch(r"[Hh]eading\s*([1-9])", val)
    if m:
        return int(m.group(1))
    if val.lower() in {"title"}:
        return 1
    return None


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _p(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t xml:space=\"preserve\">{_esc(text)}</w:t></w:r></w:p>"


def _table(rows: list[list[str]]) -> str:
    out = [
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
        '<w:tblW w:w="0" w:type="auto"/>'
        '<w:tblBorders>'
        + "".join(
            f'<w:{e} w:val="single" w:sz="4" w:color="BFBFBF"/>'
            for e in ("top", "left", "bottom", "right", "insideH", "insideV")
        )
        + "</w:tblBorders></w:tblPr>"
    ]
    for row in rows:
        out.append("<w:tr>")
        for cell in row:
            out.append(
                '<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>'
                + _p(cell) + "</w:tc>"
            )
        out.append("</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def image_blocks(blocks: list[Block]) -> list[Block]:
    return [b for b in blocks if b.kind == "image" and b.image is not None]


@dataclass(frozen=True)
class Carried:
    """One picture as it will appear in the rebuilt package."""

    rel_id: str        # rId2 upwards; rId1 is always the stylesheet
    part_name: str     # where it is written, e.g. word/media/image1.png
    image: Image

    @property
    def target(self) -> str:
        """The relationship target, which is relative to `word/`."""
        return self.part_name.split("word/", 1)[-1]


@dataclass(frozen=True)
class Dropped:
    """One picture that could not be written, and the reason a reader gets."""

    image: Image
    reason: str


@dataclass(frozen=True)
class MediaPlan:
    carried: dict[str, Carried]        # keyed by the ORIGINAL member name
    dropped: list[Dropped]


def plan_media(blocks: list[Block]) -> MediaPlan:
    """Decide what each recovered picture is called in the rebuild, and whether
    it can be written at all.

    Two things are settled here, together, because they are the same decision:

    * **The name is reissued, not carried over.** The original member name comes
      out of a damaged archive under somebody else's control. It has been seen
      to contain a quote (which breaks the relationship XML), a `..` segment
      (which walks out of `word/media/` when anything extracts the result), and
      an extension that disagrees with the bytes. None of that is content — the
      name of a picture part is plumbing nobody reads — so it is replaced with a
      plain `word/media/imageN.<ext>` and the bytes are kept exactly.
    * **The extension comes from the bytes.** `[Content_Types].xml` must declare
      a type for every extension in the package. It used to declare only the
      ones it recognised while the writer wrote the part regardless, so a
      picture Word stores as `.wdp` produced a rebuild Word itself calls
      corrupt. A format we cannot name is now refused and reported, because
      handing somebody a second unopenable file is worse than handing them a
      file with one picture missing and a line saying so.

    Keyed by original member name, so one picture used twice is carried once and
    referenced twice — which is how the original stored it.
    """
    carried: dict[str, Carried] = {}
    dropped: list[Dropped] = []
    seen: set[str] = set()
    for b in image_blocks(blocks):
        img = b.image
        if img.name in carried or img.name in seen:
            continue
        if not img.complete:
            seen.add(img.name)
            dropped.append(Dropped(img, "it was cut short by the damage and only "
                                        "part of it could be read"))
            continue
        if not img.ext:
            seen.add(img.name)
            dropped.append(Dropped(img, "it is in a picture format this rebuild "
                                        "cannot declare, so including it would "
                                        "have produced a file Word refuses to open"))
            continue
        n = len(carried) + 1
        carried[img.name] = Carried(
            rel_id=f"rId{n + 1}",
            part_name=f"{media.MEDIA_DIR}image{n}.{img.ext}",
            image=img,
        )
    return MediaPlan(carried=carried, dropped=dropped)


def build_document_xml(blocks: list[Block], plan: MediaPlan | None = None) -> str:
    plan = plan if plan is not None else plan_media(blocks)
    body = []
    for n, b in enumerate(blocks, 1):
        if b.kind == "image" and b.image is not None:
            got = plan.carried.get(b.image.name)
            # A picture the plan refused is not referenced either. A drawing
            # pointing at a part that was not written is a broken file.
            if got is None:
                continue
            body.append(media.drawing_xml(got.rel_id, b.image, n,
                                          got.part_name.rsplit("/", 1)[-1]))
        elif b.kind == "heading":
            body.append(_p(b.text, f"Heading{min(max(b.level, 1), 3)}"))
        elif b.kind == "table" and b.rows:
            body.append(_table(b.rows))
            body.append(_p(""))
        else:
            body.append(_p(b.text))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
        ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
        ' xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
        ' xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<w:body>" + "".join(body) +
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>"
    )


def write_docx(blocks: list[Block], plan: MediaPlan | None = None) -> bytes:
    import io

    plan = plan if plan is not None else plan_media(blocks)
    carried = list(plan.carried.values())

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype-equivalent ordering is not required for OOXML, but the
        # content types part must be present and first is conventional. Every
        # extension written below is declared here -- the two lists are built
        # from the same plan precisely so they cannot drift apart again.
        z.writestr("[Content_Types].xml",
                   content_types([c.image.ext for c in carried]))
        z.writestr("_rels/.rels", ROOT_RELS)
        # document.xml goes early, as Word writes it. The order is not
        # cosmetic: a truncated download loses the END of the file, so the part
        # carrying the content is the one you want furthest from the cut.
        z.writestr("word/document.xml", build_document_xml(blocks, plan))
        z.writestr("word/_rels/document.xml.rels",
                   doc_rels([(c.rel_id, c.target) for c in carried]))
        z.writestr("word/styles.xml", STYLES)
        for c in carried:
            # Already compressed. Deflating a PNG again costs time and saves
            # nothing, and this runs while somebody is watching a progress bar.
            z.writestr(c.part_name, c.image.data, zipfile.ZIP_STORED)
    return buf.getvalue()


def blocks_to_html(blocks: list[Block], inline_images: bool = False,
                   image_budget: int = 3_000_000) -> str:
    """For the SuperDocs path, which takes documents and HTML, never raw
    Word XML -- the docs are explicit that there is no endpoint for that.

    `inline_images` is for the preview the page shows before anybody downloads
    anything: the pictures have to be visible for the preview to answer the
    question it exists to answer. They are embedded as data URIs up to a budget,
    and past it the image is named rather than shown -- an image that silently
    fails to load in a preview would read as an image that was not recovered.
    """
    out = []
    spent = 0
    for b in blocks:
        if b.kind == "image" and b.image is not None:
            # The same refusal the writer makes, for the same reason: a picture
            # that is half-read or in a format we cannot name renders as a
            # broken image, and a broken image in the preview reads as a picture
            # that was not recovered rather than one that could not be shown.
            if not b.image.writable:
                continue
            if not inline_images:
                continue
            if spent + len(b.image.data) > image_budget:
                out.append(
                    '<p class="image-omitted">An image was recovered and is in '
                    "the file. It is not shown here because the preview would be "
                    "too large to load.</p>"
                )
                continue
            spent += len(b.image.data)
            src = ("data:" + b.image.content_type + ";base64,"
                   + base64.b64encode(b.image.data).decode("ascii"))
            out.append(f'<img src="{src}" alt="A picture recovered from your document">')
        elif b.kind == "heading":
            lvl = min(max(b.level, 1), 3)
            out.append(f"<h{lvl}>{_esc(b.text)}</h{lvl}>")
        elif b.kind == "table" and b.rows:
            rows = "".join(
                "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>"
                for r in b.rows
            )
            out.append(f"<table>{rows}</table>")
        else:
            out.append(f"<p>{_esc(b.text)}</p>")
    return "\n".join(out)
