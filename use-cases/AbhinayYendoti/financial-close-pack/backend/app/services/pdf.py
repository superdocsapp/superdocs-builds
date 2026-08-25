"""Minimal PDF writer (stdlib only).

Used for two things that used to be faked:
  * the synthetic demo source documents, which are now real, openable PDFs rather
    than filenames attached to nothing;
  * the checklist / sign-off / audit sheets placed inside the exported pack.

Deliberately tiny: one page size, one Type1 base font, no images or compression.
"""

from typing import Iterable

_PAGE_WIDTH = 612
_PAGE_HEIGHT = 792
_LEFT = 64
_TOP = 728
_LEADING = 16
_MAX_LINES_PER_PAGE = 40


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _sanitize(text: str) -> str:
    # The base-14 fonts are single byte; drop anything outside Latin-1.
    return "".join(char if 32 <= ord(char) < 127 else "?" for char in text)


def _content_stream(title: str, lines: Iterable[str]) -> bytes:
    parts = [
        "BT",
        f"/F1 16 Tf {_LEFT} {_TOP} Td {_LEADING} TL",
        f"({_escape(_sanitize(title))}) Tj",
        "T* T*",
        "/F2 11 Tf",
    ]
    for line in lines:
        parts.append(f"({_escape(_sanitize(line))}) Tj")
        parts.append("T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1", "replace")


def build_pdf(title: str, lines: Iterable[str]) -> bytes:
    body = _content_stream(title, list(lines)[:_MAX_LINES_PER_PAGE])

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + f"{_PAGE_WIDTH} {_PAGE_HEIGHT}".encode("ascii")
            + b"] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(body)).encode("ascii") + b" >>\nstream\n" + body + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode("ascii") + payload + b"\nendobj\n"

    xref_offset = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    return bytes(out)
