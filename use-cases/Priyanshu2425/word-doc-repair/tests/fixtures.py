"""Building blocks for the picture tests.

A real PNG rather than a checked-in blob, and a real `.docx` written by the
package's own writer, so a failure names the fault it was meant to survive
rather than "the fixture is wrong".
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib

from docrepair import docx, media
from docrepair.docx import Block
from docrepair.media import Image

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
WP = ('xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/'
      'wordprocessingDrawing"')
PIC = 'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"'


def png(width: int = 8, height: int = 6) -> bytes:
    """A real PNG, built here rather than checked in as base64."""
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + bytes([200, 40, 40] * width) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


def picture(name: str = "word/media/image1.png", data: bytes | None = None) -> Image:
    blob = png() if data is None else data
    return Image(name=name, data=blob, width_px=8, height_px=6,
                 measured=True, complete=media.is_complete(blob))


def illustrated() -> bytes:
    """A healthy document with a heading, a picture, a table and a paragraph."""
    img = picture()
    return docx.write_docx([
        Block("heading", "Site inspection", 1),
        Block("paragraph", "The east elevation, photographed on arrival:"),
        Block("image", text=img.name, image=img),
        Block("table", rows=[["Region", "Revenue"], ["EMEA", "1.2M"]]),
        Block("paragraph", "No further defects were observed."),
    ])


def drawing(rel_id: str) -> str:
    """A minimal inline drawing referencing `rel_id`."""
    return ('<w:r><w:drawing><wp:inline><wp:extent cx="100" cy="100"/>'
            '<wp:docPr id="1" name="p"/><a:graphic><a:graphicData><pic:pic>'
            f'<pic:blipFill><a:blip r:embed="{rel_id}"/></pic:blipFill>'
            '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')


def package(body: str, rels: bytes, media_parts: dict[str, bytes]) -> bytes:
    """A `.docx` assembled from raw parts, for shapes the writer will not emit."""
    doc = (f'<?xml version="1.0"?><w:document {W} {R} {A} {WP} {PIC}>'
           f"<w:body>{body}<w:sectPr/></w:body></w:document>").encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", docx.content_types(["png"]))
        z.writestr("_rels/.rels", docx.ROOT_RELS)
        z.writestr("word/document.xml", doc)
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("word/styles.xml", docx.STYLES)
        for name, blob in media_parts.items():
            z.writestr(name, blob)
    return buf.getvalue()


def rels(pairs: dict[str, str], external: set[str] | None = None) -> bytes:
    external = external or set()
    out = ['<?xml version="1.0"?><Relationships xmlns="http://schemas.'
           'openxmlformats.org/package/2006/relationships">']
    for rid, target in pairs.items():
        mode = ' TargetMode="External"' if rid in external else ""
        out.append(f'<Relationship Id="{rid}" Target="{target}"{mode}/>')
    out.append("</Relationships>")
    return "".join(out).encode()


def media_names(blob: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return sorted(n for n in z.namelist() if n.startswith("word/media/"))


def part(blob: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return z.read(name)
