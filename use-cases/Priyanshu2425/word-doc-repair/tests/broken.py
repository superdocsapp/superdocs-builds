"""Deliberately messy DOCX files — the reviewer's stated test.

Each function breaks a *healthy* document in one recognisable way, so a test
failure names the fault it was meant to survive.
"""

from __future__ import annotations

import io
import zipfile

from docrepair import docx


def healthy() -> bytes:
    return docx.write_docx([
        docx.Block("heading", "Quarterly Report", 1),
        docx.Block("paragraph", "Revenue rose in Q3 — driven by renewals & upsell."),
        docx.Block("heading", "Regional breakdown", 2),
        docx.Block("table", rows=[["Region", "Revenue"], ["EMEA", "1.2M"], ["APAC", "0.8M"]]),
        docx.Block("paragraph", "Prepared by the finance team."),
    ])


def _rewrite(data: bytes, changes: dict[str, bytes | None]) -> bytes:
    """Rebuild the archive with parts replaced (or dropped when value is None)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, \
            zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            if name in changes:
                if changes[name] is None:
                    continue
                dst.writestr(name, changes[name])
            else:
                dst.writestr(name, src.read(name))
        for name, val in changes.items():
            if val is not None and name not in src.namelist():
                dst.writestr(name, val)
    return buf.getvalue()


def truncated_container() -> bytes:
    """A cut-off download. The central directory lives at the end of a ZIP, so
    this is the classic "Word says the file is corrupt" case."""
    data = healthy()
    return data[: int(len(data) * 0.6)]


def missing_content_types() -> bytes:
    return _rewrite(healthy(), {"[Content_Types].xml": None})


def unclosed_tags() -> bytes:
    """document.xml cut mid-element."""
    with zipfile.ZipFile(io.BytesIO(healthy())) as z:
        body = z.read("word/document.xml")
    return _rewrite(healthy(), {"word/document.xml": body[: int(len(body) * 0.7)]})


def bare_ampersand_and_control_chars() -> bytes:
    with zipfile.ZipFile(io.BytesIO(healthy())) as z:
        body = z.read("word/document.xml")
    broken = body.replace(b"renewals &amp; upsell", b"renewals & upsell\x07\x00")
    return _rewrite(healthy(), {"word/document.xml": broken})


def missing_document_part() -> bytes:
    return _rewrite(healthy(), {"word/document.xml": None})


def not_a_zip_at_all() -> bytes:
    return b"This was never a Word document." * 40


def empty_body() -> bytes:
    body = (b'<?xml version="1.0"?><w:document '
            b'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b"<w:body></w:body></w:document>")
    return _rewrite(healthy(), {"word/document.xml": body})


# -- a document with pictures and page furniture ----------------------------
#
# The fixtures above are text, headings and a table, because that was what the
# rebuild carried. A document that loses its photographs loses something its
# owner will have to go and find again, so the fixtures now include some.

def _png(width: int = 8, height: int = 6) -> bytes:
    """A real PNG, built here rather than checked in as base64.

    Small enough to be free and genuine enough that the size read out of its
    header is a fact rather than a fixture constant.
    """
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + bytes([200, 40, 40] * width) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


PICTURE = _png()

_ASIDE = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:{root} xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:{root}>"
)


def illustrated() -> bytes:
    """A healthy document with a picture, a header, a footer and a footnote."""
    base = docx.write_docx([
        docx.Block("heading", "Site inspection", 1),
        docx.Block("paragraph", "The east elevation, photographed on arrival:"),
        docx.Block("image", text="word/media/image1.png",
                   image=docx.Image(name="word/media/image1.png", data=PICTURE,
                                    width_px=8, height_px=6, measured=True)),
        docx.Block("paragraph", "No further defects were observed."),
    ])
    with zipfile.ZipFile(io.BytesIO(base)) as z:
        types = z.read("[Content_Types].xml").decode()
    overrides = "".join(
        f'<Override PartName="/{part}" ContentType="{ct}"/>'
        for part, ct in (
            ("word/header1.xml", "application/vnd.openxmlformats-officedocument."
                                 "wordprocessingml.header+xml"),
            ("word/footer1.xml", "application/vnd.openxmlformats-officedocument."
                                 "wordprocessingml.footer+xml"),
            ("word/footnotes.xml", "application/vnd.openxmlformats-officedocument."
                                   "wordprocessingml.footnotes+xml"),
        )
    )
    return _rewrite(base, {
        "[Content_Types].xml": types.replace("</Types>", overrides + "</Types>").encode(),
        "word/header1.xml": _ASIDE.format(root="hdr", text="Inspection report — draft")
            .encode(),
        "word/footer1.xml": _ASIDE.format(root="ftr", text="Page 1 of 1").encode(),
        "word/footnotes.xml": _ASIDE.format(
            root="footnotes",
            text="Measurements taken with a laser rangefinder.").encode(),
    })


def truncated_illustrated() -> bytes:
    """The common case, on a document that has something to lose."""
    data = illustrated()
    return data[: int(len(data) * 0.85)]


def illustrated_without_its_map() -> bytes:
    """The picture survives; the part saying where it belonged does not."""
    return _rewrite(illustrated(), {"word/_rels/document.xml.rels": None})
