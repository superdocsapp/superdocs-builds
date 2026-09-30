"""Every place text hides in a `.docx`, read straight from the package.

`Office.js` and `python-docx` both give the body, and the four things a records
officer gets caught by are not in the body:

    word/header1.xml     a name on every page's letterhead
    word/footer1.xml     a matter reference
    word/comments.xml    "call Dmitri about card 4111 1111 1111 1111"
    <w:delText>          a tracked deletion — struck through, still in the file

The last two are invisible in Word's default view and survive export
(`fixtures/superdocs_responses/13_hidden_export.docx` carries both; a body-only
pane would call it clean). We don't route the scan through SuperDocs either: no
recorded response shows a comment or tracked deletion in its parsed HTML, so
reading the package ourselves is deterministic, needs no key/network/quota, and
tests offline.

Offsets are into the block text — `text[start:end]` is the span, the same
contract `pii/patterns.py` and the LLM tier hold to.

See extensions/redaction-pane/README.md § "How it finds things".
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

BODY = "word/document.xml"

_HEADER = re.compile(r"^word/header\d*\.xml$")
_FOOTER = re.compile(r"^word/footer\d*\.xml$")

PART_TYPES: tuple[tuple[str, object], ...] = (
    ("body", BODY),
    ("header", _HEADER),
    ("footer", _FOOTER),
    ("footnote", "word/footnotes.xml"),
    ("endnote", "word/endnotes.xml"),
    ("comment", "word/comments.xml"),
)
"""In display order: the document first, then the places somebody has to be told
about. Header/footer are patterns because Word numbers them per section
(`header1.xml`, `header2.xml`…)."""

TRACKED_DELETION = "tracked_del"
"""Its own part type. A tracked deletion can't be redacted in place — Word's
`search` doesn't match struck-through text — so `office.ts` reports it
unredactable and says why; "in your file but not your document" is fixed
differently from "in your document". Tracked *insertions* get no equivalent:
their text is ordinary visible `<w:t>`, so it is reported as body text."""


@dataclass(frozen=True, slots=True)
class Block:
    chunk_id: str
    """`document:12`, `comments:0`, `header1:3`, `document:7#del`. From the part
    and the paragraph's position, so an unchanged document scans to the same
    ids."""
    part_type: str
    text: str

    def as_tuple(self) -> tuple[str, str, str]:
        """What `service/pii/engine.scan` takes."""
        return (self.chunk_id, self.part_type, self.text)


class UnreadableDocument(Exception):
    """The bytes are neither a Word package nor decodable text."""


def read(data: bytes) -> list[Block]:
    """Bytes from the open document → every block. Accepts plain text as well as
    `.docx`, because `FakeHost` hands the pane text outside Word and a scan that
    only worked inside Word could not be tested."""
    if data[:2] == b"PK":
        return read_docx(data)
    return read_text(data)


def read_docx(data: bytes) -> list[Block]:
    try:
        package = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:  # pragma: no cover - guarded by read()
        raise UnreadableDocument(f"not a readable .docx — {exc}") from exc

    names = set(package.namelist())
    if BODY not in names:
        raise UnreadableDocument("not a Word document — no word/document.xml")

    blocks: list[Block] = []
    for part_type, matcher in PART_TYPES:
        for name in sorted(_matching(names, matcher)):
            try:
                xml = package.read(name)
            except KeyError:  # pragma: no cover - name came from the listing
                continue
            blocks.extend(_part(xml, name=name, part_type=part_type))
    return blocks


def read_text(data: bytes) -> list[Block]:
    """A plain-text fallback: one block per blank-line-separated paragraph."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception as exc:  # pragma: no cover
            raise UnreadableDocument(f"could not be decoded as text — {exc}") from exc
    return [
        Block(chunk_id=f"text:{index}", part_type="body", text=paragraph)
        for index, paragraph in enumerate(re.split(r"\n[ \t]*\n", text))
        if paragraph.strip()
    ]


def _matching(names: set[str], matcher: object) -> list[str]:
    if isinstance(matcher, str):
        return [matcher] if matcher in names else []
    pattern: re.Pattern[str] = matcher  # type: ignore[assignment]
    return [name for name in names if pattern.match(name)]


def _part(xml: bytes, *, name: str, part_type: str) -> list[Block]:
    """One XML part → its paragraphs, visible and deleted text separately. One
    paragraph can yield two blocks: *"Contact ~~Harold Vance~~ Susan Reyes"* has
    a visible half and a struck-through half, different strings, only one
    clickable in Word. Splitting keeps offsets honest — interleaving them would
    produce a string that appears nowhere."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        # A malformed sibling part must not lose us the body.
        return []

    stem = name.rsplit("/", 1)[-1].removesuffix(".xml")
    blocks: list[Block] = []
    # `.iter()` is document order, so a paragraph inside a table lands where it
    # reads rather than after everything else.
    for index, paragraph in enumerate(root.iter(f"{W}p")):
        visible, deleted = _paragraph(paragraph)
        if visible.strip():
            blocks.append(Block(chunk_id=f"{stem}:{index}", part_type=part_type, text=visible))
        if deleted.strip():
            blocks.append(
                Block(
                    chunk_id=f"{stem}:{index}#del",
                    part_type=TRACKED_DELETION,
                    text=deleted,
                )
            )
    return blocks


def _paragraph(paragraph: ElementTree.Element) -> tuple[str, str]:
    """`(visible, deleted)`. `<w:t>` is in-document text, `<w:delText>` is struck
    through and kept in the file. Two strings give the accepted-changes and
    deleted views in one pass, with no special-casing of `<w:ins>` (its runs are
    ordinary `<w:t>`). Tabs and breaks are kept, or a span crossing one would not
    match at its offsets."""
    visible: list[str] = []
    deleted: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{W}t":
            visible.append(node.text or "")
        elif node.tag == f"{W}delText":
            deleted.append(node.text or "")
        elif node.tag == f"{W}tab":
            visible.append("\t")
        elif node.tag in (f"{W}br", f"{W}cr"):
            visible.append("\n")
    return "".join(visible), "".join(deleted)


def coverage(blocks: list[Block]) -> dict[str, int]:
    """Blocks per part type, shown after a scan. "Nothing found across 41 body
    blocks, 2 headers and 1 comment" is checkable; "nothing found" alone is
    not."""
    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.part_type] = counts.get(block.part_type, 0) + 1
    return counts
