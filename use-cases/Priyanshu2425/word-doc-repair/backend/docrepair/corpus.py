"""The measured corpus: real documents, one named fault each, and the truth.

`tests/broken.py` breaks one document eight ways so a failing test names the
fault it was meant to survive. That is a *test* corpus — it answers "does this
still work", not "how much comes back". This module answers the second question,
and it needs three things that one do not:

**Documents this package did not write.** A repair tool tested only against its
own output is tested against its own assumptions. Three of the five base
documents here were authored by other software — Google Docs, Apple's
`textutil`, and the converter behind the Open Preservation Foundation's
`variations` set — and their XML is laid out in ways this package would never
produce.

**Damage sorted by what it destroys**, because a recovery rate that mixes the
two kinds is not a number about anything. A missing `[Content_Types].xml`
removes no words: anything short of full recovery is a defect. A download cut
off at 30% removes most of them: full recovery is impossible and claiming it
would be a lie. Those cannot share a denominator, so they do not — see
`Damage.kind`.

**Ground truth that the repair path had no hand in.** `text_of` scrapes `<w:t>`
runs out of a document part with the standard library and nothing else. It reads
the intact original to get the truth and the rebuilt file to get the result, so
both sides of every ratio are measured by the same function, and that function
shares no code with the thing being measured.
"""

from __future__ import annotations

import io
import re
import warnings
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import docx
from .docx import Block, Image

#: Where the vendored originals live. Outside the package, because they are
#: corpus data rather than code, and a wheel has no business carrying half a
#: megabyte of other people's documents.
ORIGINALS = Path(__file__).resolve().parents[2] / "corpus" / "originals"

DOCUMENT_PART = "word/document.xml"

#: A text run, or a boundary that separates one word from the next.
#:
#: `<w:t(?:\s[^>]*)?>` and deliberately not `<w:t[^>]*>` -- the unanchored form
#: also matches `<w:tbl>`, `<w:tr>` and `<w:tc>` and swallows a table's markup
#: as if it were text. And the boundaries matter as much as the runs: Word
#: splits a word across runs whenever the formatting changes mid-word, so runs
#: inside a paragraph join with nothing between them, while a paragraph or a
#: cell ending is a space. Both of these were defects in this module before
#: they were comments in it -- the first made a Google Docs file look 84%
#: unrecovered, the second turned *adipiscing* into two words the rebuild was
#: then blamed for losing.
_PIECE = re.compile(
    rb"<w:t(?:\s[^>]*)?>(.*?)</w:t>"
    rb"|(</w:p>|</w:tc>|<w:br\s*/>|<w:tab\s*/>)", re.DOTALL)
_ENTITY = {b"&amp;": b"&", b"&lt;": b"<", b"&gt;": b">",
           b"&quot;": b'"', b"&apos;": b"'"}


# -- ground truth, measured by something that is not the repair engine -------

def text_of(data: bytes) -> str:
    """Every word in a document part, read with the standard library alone.

    Deliberately naive: find the text runs, unescape the five XML entities,
    join. It cannot be right about formatting and does not try — it is a
    yardstick, and a yardstick that shares code with the thing it measures is
    not one.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if DOCUMENT_PART not in z.namelist():
                return ""
            body = z.read(DOCUMENT_PART)
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return ""
    out: list[str] = []
    for run, boundary in _PIECE.findall(body):
        if boundary:
            out.append(" ")
            continue
        for src, dst in _ENTITY.items():
            run = run.replace(src, dst)
        out.append(run.decode("utf-8", "replace"))
    return "".join(out)


def words(text: str) -> Counter:
    """Words, case-folded and stripped of punctuation that carries no meaning.

    A multiset rather than a set: a document that says "revenue" four times and
    comes back saying it once has lost something, and a set would report that as
    perfect.
    """
    return Counter(w for w in re.findall(r"[\w'-]+", text.lower()) if w)


def recall(truth: str, got: str) -> float:
    """The share of the original's words present in the recovered text."""
    t, g = words(truth), words(got)
    if not t:
        return 1.0
    return sum((t & g).values()) / sum(t.values())


def counts_of(data: bytes) -> dict[str, int]:
    """Structure a reader would notice going missing."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            body = z.read(DOCUMENT_PART) if DOCUMENT_PART in names else b""
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return {"tables": 0, "rows": 0, "images": 0}
    return {
        "tables": body.count(b"<w:tbl>"),
        "rows": body.count(b"<w:tr>") + body.count(b"<w:tr "),
        # Counted by what the bytes are, not by what the archive lists. A member
        # under word/media/ that stops before its format's end marker is a grey
        # box in Word, and counting it as a recovered picture is the harness
        # agreeing with a claim the file cannot support.
        "images": _readable_images(names, data),
    }


def _readable_images(names: list[str], data: bytes) -> int:
    from . import media

    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in names:
                if not n.startswith("word/media/"):
                    continue
                try:
                    blob = z.read(n)
                except (KeyError, zipfile.BadZipFile, RuntimeError, OSError):
                    continue
                if media.sniff_ext(blob) and media.is_complete(blob):
                    total += 1
    except (zipfile.BadZipFile, OSError, RuntimeError):
        return 0
    return total


# -- the five base documents -------------------------------------------------

@dataclass(frozen=True)
class Base:
    name: str
    written_by: str
    source: str
    make: object          # () -> bytes
    _cache: dict = field(default_factory=dict, compare=False, repr=False)

    def bytes(self) -> bytes:
        if "b" not in self._cache:
            self._cache["b"] = self.make()
        return self._cache["b"]


def _png(width: int = 8, height: int = 6) -> bytes:
    """A real PNG, built here rather than checked in as base64."""
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


def _report() -> bytes:
    return docx.write_docx([
        Block("heading", "Quarterly Report", 1),
        Block("paragraph", "Revenue rose in Q3 — driven by renewals & upsell."),
        Block("heading", "Regional breakdown", 2),
        Block("table", rows=[["Region", "Revenue"], ["EMEA", "1.2M"], ["APAC", "0.8M"]]),
        Block("paragraph", "Prepared by the finance team."),
    ])


def _illustrated() -> bytes:
    picture = _png()
    return docx.write_docx([
        Block("heading", "Site inspection", 1),
        Block("paragraph", "The east elevation, photographed on arrival:"),
        Block("image", text="word/media/image1.png",
              image=Image(name="word/media/image1.png", data=picture,
                          width_px=8, height_px=6, measured=True)),
        Block("paragraph", "No further defects were observed."),
    ])


def _vendored(filename: str):
    def read() -> bytes:
        path = ORIGINALS / filename
        if not path.exists():
            raise FileNotFoundError(
                f"{path} is missing. The measured corpus needs the vendored "
                f"originals; see corpus/originals/README.md for what they are "
                f"and where they came from."
            )
        return path.read_bytes()
    return read


BASES: list[Base] = [
    Base("synthetic-report", "this package",
         "generated at run time", _report),
    Base("synthetic-illustrated", "this package",
         "generated at run time", _illustrated),
    Base("apple-textutil", "Apple textutil (macOS)",
         "corpus/originals/apple-textutil.docx", _vendored("apple-textutil.docx")),
    Base("opf-lorem-ipsum", "the OPF variations converter",
         "corpus/originals/opf-lorem-ipsum.docx", _vendored("opf-lorem-ipsum.docx")),
    Base("gdocs-fully-featured", "Google Docs",
         "corpus/originals/gdocs-fully-featured.docx",
         _vendored("gdocs-fully-featured.docx")),
]


# -- damage ------------------------------------------------------------------

LOSSLESS = "lossless"     # every word is still in the bytes; full recovery is owed
LOSSY = "lossy"           # bytes were physically removed; partial is the honest answer
FATAL = "fatal"           # the content is not there; refusing is the only right answer


def _rewrite(data: bytes, changes: dict[str, bytes | None]) -> bytes:
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


def _body(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return z.read(DOCUMENT_PART)


def _media_names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return [n for n in z.namelist() if n.startswith("word/media/")]


def _cut(fraction: float):
    def damage(data: bytes) -> bytes:
        return data[: int(len(data) * fraction)]
    return damage


def _missing_content_types(data: bytes) -> bytes:
    return _rewrite(data, {"[Content_Types].xml": None})


def _missing_rels(data: bytes) -> bytes:
    return _rewrite(data, {"word/_rels/document.xml.rels": None})


def _bad_characters(data: bytes) -> bytes:
    """A bare ampersand and two control characters — the classic hand-edit."""
    body = _body(data)
    hit = body.replace(b"&amp;", b"&", 1)
    if hit == body:                       # no entity to spoil; spoil a tag boundary
        hit = body.replace(b"</w:t>", b"\x07\x00</w:t>", 1)
    else:
        hit = hit.replace(b"</w:t>", b"\x07\x00</w:t>", 1)
    return _rewrite(data, {DOCUMENT_PART: hit})


def _mangled_declaration(data: bytes) -> bytes:
    body = _body(data)
    if body.startswith(b"<?xml"):
        end = body.index(b"?>") + 2
        body = b'<?xml version="1.0" encoding="UTF-42" standalon=yes?>' + body[end:]
    else:
        body = b'<?xml version="1.0" encoding="UTF-42"?>' + body
    return _rewrite(data, {DOCUMENT_PART: body})


def _garbage_prefix(data: bytes) -> bytes:
    """What a mail client or a proxy leaves in front of an attachment."""
    return (b"HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n\r\n"
            + data)


def _zeroed_eocd(data: bytes) -> bytes:
    """The index is destroyed and every byte of content is still present.

    This is the case the whole salvage path exists for, made deliberate: a ZIP
    reader refuses the file outright, while the local file headers it never
    reaches are all intact.
    """
    idx = data.rfind(b"PK\x05\x06")
    if idx == -1:
        return data
    return data[:idx] + b"XX\x05\x06" + data[idx + 4:]


def _duplicate_entry(data: bytes) -> bytes:
    """A second, corrupt copy of the body under the same name — CVE-2025-31672's
    shape, and a real disagreement about which entry a reader takes."""
    buf = io.BytesIO()
    with warnings.catch_warnings():
        # zipfile warns about the duplicate name. Writing one is the point here.
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(io.BytesIO(data)) as src, \
                zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
            for name in src.namelist():
                dst.writestr(name, src.read(name))
            dst.writestr(DOCUMENT_PART, b"<?xml version='1.0'?><w:document/>")
    return buf.getvalue()


def _bad_crc(data: bytes) -> bytes:
    """The stored checksum for the body no longer matches its bytes.

    Nothing is lost — a reader that trusts the CRC refuses a file that is
    entirely readable.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo(DOCUMENT_PART)
        offset = info.header_offset
    out = bytearray(data)
    crc_at = offset + 14                       # local file header: CRC-32 field
    out[crc_at:crc_at + 4] = b"\x00\x00\x00\x00"
    return bytes(out)


def _unclosed_tags(data: bytes) -> bytes:
    body = _body(data)
    return _rewrite(data, {DOCUMENT_PART: body[: int(len(body) * 0.7)]})


def _body_bitrot(data: bytes) -> bytes:
    """Bit flips inside the compressed body — the damage a failing disk does."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo(DOCUMENT_PART)
        start = info.header_offset + 30 + len(info.filename) + len(info.extra)
    out = bytearray(data)
    span = max(1, info.compress_size // 3)
    for i in range(start + span, min(start + span + 24, len(out))):
        out[i] ^= 0xFF
    return bytes(out)


def _media_truncated(data: bytes) -> bytes:
    names = _media_names(data)
    if not names:
        return data
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        raw = z.read(names[0])
    return _rewrite(data, {names[0]: raw[: len(raw) // 2]})


def _missing_document_part(data: bytes) -> bytes:
    return _rewrite(data, {DOCUMENT_PART: None})


def _zero_length_body(data: bytes) -> bytes:
    return _rewrite(data, {DOCUMENT_PART: b""})


def _not_a_zip(data: bytes) -> bytes:
    return b"This was never a Word document." * 40


def _empty_body(data: bytes) -> bytes:
    return _rewrite(data, {DOCUMENT_PART: (
        b'<?xml version="1.0"?><w:document '
        b'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b"<w:body></w:body></w:document>")})


@dataclass(frozen=True)
class Damage:
    name: str
    kind: str
    apply: object            # (bytes) -> bytes
    what_happened: str
    #: Damage that only means something on a document with pictures.
    needs_media: bool = False


DAMAGES: list[Damage] = [
    # Lossless — every word survives in the bytes. Anything short of full
    # recovery here is this tool's fault and nobody else's.
    Damage("missing-content-types", LOSSLESS, _missing_content_types,
           "the part that tells Word what the other parts are is gone"),
    Damage("missing-rels", LOSSLESS, _missing_rels,
           "the part that says where each picture belonged is gone"),
    Damage("bad-characters", LOSSLESS, _bad_characters,
           "a bare ampersand and two control characters in the body"),
    Damage("mangled-xml-declaration", LOSSLESS, _mangled_declaration,
           "the body declares an encoding that does not exist"),
    Damage("garbage-prefix", LOSSLESS, _garbage_prefix,
           "an HTTP response header left in front of the file"),
    Damage("zeroed-eocd", LOSSLESS, _zeroed_eocd,
           "the archive's index signature is destroyed; the content is untouched"),
    Damage("duplicate-entry", LOSSLESS, _duplicate_entry,
           "a second, empty copy of the body under the same name"),
    Damage("bad-crc", LOSSLESS, _bad_crc,
           "the stored checksum for the body no longer matches its bytes"),

    # Lossy — bytes were physically removed. Partial recovery is the honest
    # answer and full recovery is not available at any price.
    Damage("truncated-90", LOSSY, _cut(0.90), "the download stopped at 90%"),
    Damage("truncated-60", LOSSY, _cut(0.60), "the download stopped at 60%"),
    Damage("truncated-30", LOSSY, _cut(0.30), "the download stopped at 30%"),
    Damage("unclosed-tags", LOSSY, _unclosed_tags,
           "the body is cut off mid-element"),
    Damage("body-bitrot", LOSSY, _body_bitrot,
           "bit flips inside the compressed body"),
    Damage("media-truncated", LOSSY, _media_truncated,
           "a picture's bytes are cut in half", True),

    # Fatal — the words are not in the file. Refusing is the only right answer,
    # and a cheerful success here would be the worst output this tool can give.
    Damage("missing-document-part", FATAL, _missing_document_part,
           "the body part is gone entirely"),
    Damage("zero-length-body", FATAL, _zero_length_body,
           "the body part is present and zero bytes long"),
    Damage("not-a-zip", FATAL, _not_a_zip,
           "the file was never a Word document"),
    Damage("empty-body", FATAL, _empty_body,
           "a valid, empty document"),
]


@dataclass
class Fixture:
    name: str
    base: Base
    damage: Damage
    data: bytes
    truth_text: str
    truth_counts: dict[str, int]


def build() -> list[Fixture]:
    """The whole corpus, generated. Nothing here is checked in but the originals."""
    out: list[Fixture] = []
    for base in BASES:
        original = base.bytes()
        truth_text = text_of(original)
        truth_counts = counts_of(original)
        has_media = truth_counts["images"] > 0
        for damage in DAMAGES:
            if damage.needs_media and not has_media:
                continue
            out.append(Fixture(
                name=f"{base.name}/{damage.name}",
                base=base,
                damage=damage,
                data=damage.apply(original),
                truth_text=truth_text,
                truth_counts=truth_counts,
            ))
    return out
