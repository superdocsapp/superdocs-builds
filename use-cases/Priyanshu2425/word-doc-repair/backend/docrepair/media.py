"""Getting the pictures back.

A `.docx` keeps its images as ordinary members of the ZIP — `word/media/image1.png`
and so on — each with its own local file header, entirely separate from
`word/document.xml`. Which means they survive exactly the damage that destroys
the index, and a rebuild that drops them is throwing away bytes that were sitting
right there.

That mattered to somebody. From the research, describing a report that broke:
*"it was a report with photos and a table of numbers"* — and later, on what the
recovery cost them, *"the photos I got off my phone again — the ones I still
had."* The words came back and the pictures did not, and re-sourcing the
pictures was most of the work.

Two things this module refuses to do:

* **Guess at a size.** Word needs an explicit extent in EMUs for an inline
  image. The dimensions are read out of the image's own header — PNG, JPEG and
  GIF all carry them in the first few bytes — and an image whose header cannot
  be read gets a stated default rather than a fabricated measurement, with the
  aspect ratio left alone rather than invented.
* **Pretend it knows where a picture went.** A drawing's position is recoverable
  only when the relationship part survived to say which file the reference points
  at. When it did not, the image is still returned — at the end, under its own
  heading, with the report saying plainly that its original position could not be
  recovered. An image silently placed in the wrong paragraph is worse than an
  image obviously placed at the end.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from xml.etree import ElementTree as ET

MEDIA_DIR = "word/media/"

#: 914400 EMU to the inch, and images are authored at 96 DPI by convention.
EMU_PER_PX = 9525
#: Six inches. Wider than the text column on A4 with the margins this rebuild
#: writes, so a large photograph is scaled down rather than running off the page.
MAX_WIDTH_EMU = 6 * 914400
#: What an image gets when its header cannot be read: a square, stated as a
#: default in the code rather than presented as a measurement.
FALLBACK_PX = (480, 360)

CONTENT_TYPES = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "gif": "image/gif", "bmp": "image/bmp", "tif": "image/tiff",
    "tiff": "image/tiff", "emf": "image/x-emf", "wmf": "image/x-wmf",
    "svg": "image/svg+xml", "webp": "image/webp",
}

_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


@dataclass(frozen=True)
class Image:
    """One recovered picture."""

    name: str            # the member name inside the original, e.g. word/media/image1.png
    data: bytes
    width_px: int
    height_px: int
    measured: bool       # False when the dimensions are the stated fallback
    #: False when the bytes stop before the format's own end marker. A picture
    #: recovered only up to the break is not a picture: Word draws a placeholder
    #: where it should be, and the file claims a recovery that did not happen.
    complete: bool = True

    @property
    def ext(self) -> str:
        """The extension the bytes justify, not the one the name claims.

        A member called `.png` holding a JPEG is written by more tools than it
        should be, and a `.wdp` or a `.heic` has no OOXML content type at all.
        Declaring the wrong type — or failing to declare one — produces a
        package Word calls corrupt, which is this tool handing somebody a second
        broken file. So the bytes decide, and a format we cannot name is refused
        by `writable` rather than guessed at.
        """
        sniffed = sniff_ext(self.data)
        if sniffed:
            return sniffed
        claimed = self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""
        return claimed if claimed in CONTENT_TYPES else ""

    @property
    def writable(self) -> bool:
        """Whether this picture can go into a package that will still open."""
        return bool(self.ext) and self.complete

    @property
    def content_type(self) -> str:
        return CONTENT_TYPES.get(self.ext, "application/octet-stream")

    @property
    def extent(self) -> tuple[int, int]:
        """Width and height in EMUs, scaled to fit the page, aspect preserved."""
        w = max(1, self.width_px) * EMU_PER_PX
        h = max(1, self.height_px) * EMU_PER_PX
        if w > MAX_WIDTH_EMU:
            h = int(h * MAX_WIDTH_EMU / w)
            w = MAX_WIDTH_EMU
        return w, h


# -- reading a size out of the bytes ----------------------------------------

#: Magic numbers, longest first so a prefix never shadows a longer signature.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"\xff\xd8\xff", "jpg"),
    (b"BM", "bmp"),
    (b"II*\x00", "tif"),
    (b"MM\x00*", "tif"),
    (b"\xd7\xcd\xc6\x9a", "wmf"),
    (b"\x01\x00\x00\x00", "emf"),
)


def sniff_ext(data: bytes) -> str:
    """The format's own name for itself, or "" when the bytes do not say.

    Only formats with a declared OOXML content type are recognised, because the
    single caller wants to know what it may write into a package — and "this is
    an HD Photo" is, for that question, the same answer as "I do not know".
    """
    if not data:
        return ""
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    # RIFF....WEBP, and SVG, which is text and so has no fixed magic number.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    head = data[:512].lstrip()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:512]):
        return "svg"
    return ""


def is_complete(data: bytes) -> bool:
    """Whether the bytes run all the way to the format's own end marker.

    `salvage` deliberately keeps the prefix of a stream that went bad partway,
    which is the right call for a document body — half the words beat none of
    them. It is the wrong call for a picture, which is why the check lives here
    and not there: half a PNG is not half a photograph, it is a grey box.

    Formats without an end marker to check are taken at their word rather than
    called damaged on no evidence.
    """
    if not data:
        return False
    ext = sniff_ext(data)
    if ext == "png":
        # The IEND chunk closes the file; a trailing CRC follows it.
        return data.rstrip(b"\x00").endswith(b"IEND\xaeB`\x82")
    if ext == "jpg":
        return data.rstrip(b"\x00").endswith(b"\xff\xd9")
    if ext == "gif":
        return data.rstrip(b"\x00").endswith(b"\x3b")
    return True


def image_size(data: bytes) -> tuple[int, int] | None:
    """Width and height from the image's own header, or None.

    Deliberately hand-rolled over the three formats that account for almost
    every image in a Word document. A dependency here would be a dependency in a
    tool whose whole promise is that it runs offline, in milliseconds, for
    somebody who is already having a bad day.
    """
    if len(data) < 12:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return (w, h) if w and h else None
    if data[:3] == b"GIF":
        w, h = struct.unpack("<HH", data[6:10])
        return (w, h) if w and h else None
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Walk the segment chain to a start-of-frame marker.

    A JPEG's dimensions are not at a fixed offset — they sit in whichever SOF
    segment the encoder wrote, after any number of application and quantisation
    segments. Guessing an offset produces a plausible wrong number, which is the
    kind of wrong this tool minds most.
    """
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > n:
            return None
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        # SOF0-SOF15, excluding the four that are not frame headers.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 9 > n:
                return None
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return (w, h) if w and h else None
        if length < 2:
            return None
        i += 2 + length
    return None


def collect(members: dict[str, bytes]) -> dict[str, Image]:
    """Every image that survived, keyed by its member name."""
    out: dict[str, Image] = {}
    for name, data in members.items():
        if not name.startswith(MEDIA_DIR) or not data:
            continue
        size = image_size(data)
        out[name] = Image(
            name=name, data=data,
            width_px=size[0] if size else FALLBACK_PX[0],
            height_px=size[1] if size else FALLBACK_PX[1],
            measured=size is not None,
            complete=is_complete(data),
        )
    return out


# -- working out where they went --------------------------------------------

_REL_RE = re.compile(
    rb'Id="(?P<id>[^"]+)"[^>]*?Target="(?P<target>[^"]+)"', re.S)
_EXTERNAL_RE = re.compile(rb'TargetMode="External"')

#: Marks a target that was never inside the package. A picture linked from a URL
#: or a drive path is not a picture this file ever carried, so reporting it as
#: content lost to the damage would be telling somebody they lost something they
#: never had here. The prefix cannot collide with a member name because a member
#: name may not contain a colon at this position.
EXTERNAL = "external:"


def is_external(target: str) -> bool:
    return target.startswith(EXTERNAL)


def relationship_targets(rels_xml: bytes | None) -> dict[str, str]:
    """rId -> the member it points at, from `word/_rels/document.xml.rels`.

    Parsed properly when the part is well-formed and by regex when it is not,
    because this part is as likely to be damaged as any other and half a map is
    worth more here than none: an image whose relationship survived can go back
    where it was, and the rest are still returned at the end.
    """
    if not rels_xml:
        return {}
    targets: dict[str, str] = {}
    try:
        for rel in ET.fromstring(rels_xml):
            rid, target = rel.get("Id"), rel.get("Target")
            if rid and target:
                targets[rid] = (EXTERNAL + target
                                if rel.get("TargetMode") == "External"
                                else _normalise(target))
        return targets
    except ET.ParseError:
        for m in _REL_RE.finditer(rels_xml):
            target = m.group("target").decode("utf-8", "replace")
            # The regex pass reads one relationship element at a time, so the
            # mode is whatever sits between this Id and the end of its tag.
            tail = rels_xml[m.end():rels_xml.find(b">", m.end()) + 1]
            external = bool(_EXTERNAL_RE.search(m.group(0) + tail))
            targets[m.group("id").decode("utf-8", "replace")] = (
                EXTERNAL + target if external else _normalise(target))
        return targets


def _normalise(target: str) -> str:
    """Relationship targets are relative to `word/`, and may say so the long way."""
    target = target.lstrip("/")
    if target.startswith("word/"):
        return target
    while target.startswith("../"):
        target = target[3:]
    return f"word/{target}"


def embedded_ids(element: ET.Element) -> list[str]:
    """The relationship ids of every image referenced inside this element."""
    ids: list[str] = []
    for blip in element.iter(f"{{{_A_NS}}}blip"):
        rid = blip.get(f"{{{_R_NS}}}embed") or blip.get(f"{{{_R_NS}}}link")
        if rid:
            ids.append(rid)
    # Older documents use VML rather than DrawingML, and a picture is a picture.
    for imagedata in element.iter(
            "{urn:schemas-microsoft-com:vml}imagedata"):
        rid = imagedata.get(f"{{{_R_NS}}}id")
        if rid:
            ids.append(rid)
    return ids


def esc_attr(s: str) -> str:
    """Text made safe to sit inside a double-quoted XML attribute.

    Shared by the two places that write a name or a target read out of the
    damaged file. Both used to interpolate it raw, and a member called
    `a"b.png` was enough to produce a rebuild that would not open — the one
    failure this package exists to prevent, reintroduced by its own writer.
    """
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&apos;"))


def drawing_xml(rel_id: str, image: Image, doc_pr_id: int, name: str) -> str:
    """One inline image, as Word's own drawing markup.

    Written out longhand rather than templated from something shorter, because
    every element in it is required: Word rejects an inline drawing missing an
    extent, a docPr, a blipFill or a preset geometry, and rejecting it means the
    owner's file does not open — which is the one outcome this build exists to
    prevent.
    """
    cx, cy = image.extent
    # The name comes out of the original archive, which is exactly the input
    # this package must not trust: one quote in it and the drawing's markup is
    # malformed, which means the *repaired* file does not open either.
    name = esc_attr(name)
    return (
        "<w:p><w:r><w:drawing>"
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        f'<wp:docPr id="{doc_pr_id}" name="{name}"/>'
        "<a:graphic>"
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:pic>"
        f'<pic:nvPicPr><pic:cNvPr id="{doc_pr_id}" name="{name}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        "<pic:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr>"
        "</pic:pic></a:graphicData></a:graphic></wp:inline>"
        "</w:drawing></w:r></w:p>"
    )
