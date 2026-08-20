"""The prior-year signed statements, parsed so we can cite them and roll them on.

Two things are needed from last year's set and nothing else:

1. **Structure.** The order of the top-level elements, the note headings and
   their numbers, and the `Note` column of the primary statements. That column
   is real data - it is the note/caption cross-reference graph, supplied rather
   than supplied by us - and every repoint rides on it.
2. **Citable figures.** A comparative is only a comparative if it can be cited
   to the signed set as well as to the ledger, so every figure in the primary
   tables and in the note prose is located by byte range.

Byte offsets, not character offsets. The file is full of em dashes and
`&middot;`, and a character offset would be silently wrong from the first note
onwards - which is the failure mode that is invisible until a citation is read
back on a different machine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from .figures import Cite
from .money import money_tokens, strip_markup

TOP_LEVEL = ("h1", "h2", "h3", "p", "table")
VOID = {"br", "meta", "hr", "img", "link", "input"}

# The dash class covers em, en and hyphen: the signed set uses an em dash and a
# different engagement will not.
NOTE_HEADING = re.compile(r"^\s*Note\s+(?P<number>\d+)\s*[—–-]\s*(?P<title>.+?)\s*$")  # noqa: RUF001
CELL = re.compile(r"<t([dh])\b[^>]*>(.*?)</t\1>", re.S)
ROW = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S)
NOTE_REFERENCE = re.compile(r"\bNote\s+(\d+)\b")


class _ByteIndex:
    """Character (line, col) from HTMLParser -> absolute byte offset."""

    def __init__(self, text: str) -> None:
        self._line_start: list[int] = [0]
        self._lines: list[str] = text.splitlines(keepends=True)
        offset = 0
        for line in self._lines:
            offset += len(line.encode("utf-8"))
            self._line_start.append(offset)

    def byte_at(self, line: int, col: int) -> int:
        prefix = self._lines[line - 1][:col] if line - 1 < len(self._lines) else ""
        return self._line_start[line - 1] + len(prefix.encode("utf-8"))


@dataclass(frozen=True)
class Element:
    tag: str
    raw: str  # exact source slice, tags included
    byte_start: int
    byte_end: int

    @property
    def text(self) -> str:
        return strip_markup(self.raw).strip()

    @property
    def inner(self) -> str:
        return self.raw[self.raw.index(">") + 1 : self.raw.rindex("<")]


class _TopLevelScanner(HTMLParser):
    def __init__(self, index: _ByteIndex) -> None:
        super().__init__(convert_charrefs=False)
        self.index = index
        self.spans: list[tuple[str, int, int]] = []
        self._depth = 0
        self._open_tag: str | None = None
        self._start: int = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in VOID:
            return
        if self._open_tag is None:
            if tag in TOP_LEVEL:
                self._open_tag = tag
                self._depth = 1
                line, col = self.getpos()
                self._start = self.index.byte_at(line, col)
            return
        if tag == self._open_tag:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._open_tag is None or tag != self._open_tag:
            return
        self._depth -= 1
        if self._depth == 0:
            line, col = self.getpos()
            end = self.index.byte_at(line, col) + len(f"</{tag}>")
            self.spans.append((self._open_tag, self._start, end))
            self._open_tag = None


@dataclass(frozen=True)
class StatementRow:
    caption: str
    note_ref: int | None
    values: tuple[str, ...]  # raw cell text, current year first
    cites: tuple[Cite | None, ...]
    is_total: bool
    section: str = ""  # the enclosing section header row, e.g. "Non-current liabilities"
    is_section: bool = False


@dataclass(frozen=True)
class PrimaryStatement:
    heading: Element
    table: Element
    rows: tuple[StatementRow, ...]

    def row(self, caption: str) -> StatementRow | None:
        for candidate in self.rows:
            if candidate.caption == caption:
                return candidate
        return None


@dataclass(frozen=True)
class PriorNote:
    number: int
    title: str
    heading: Element
    body: tuple[Element, ...]

    @property
    def text(self) -> str:
        return " ".join(e.text for e in self.body)


class PriorYearSet:
    """Last year's signed statements: elements, primary statements, notes."""

    def __init__(self, path: Path, corpus_root: Path) -> None:
        self.path = path
        self.rel = path.relative_to(corpus_root).as_posix()
        raw = path.read_bytes()
        self.raw = raw
        text = raw.decode("utf-8")
        scanner = _TopLevelScanner(_ByteIndex(text))
        scanner.feed(text)
        scanner.close()
        self.elements: list[Element] = [
            Element(tag, raw[s:e].decode("utf-8"), s, e) for tag, s, e in scanner.spans
        ]
        if not self.elements:
            raise ValueError(f"{self.rel}: no top-level elements found; is this the signed set?")

        self.header: list[Element] = []
        self.statements: list[PrimaryStatement] = []
        self.notes_heading: Element | None = None
        self.notes: list[PriorNote] = []
        self._split()

    # -- structure ---------------------------------------------------------

    def _split(self) -> None:
        index = 0
        elements = self.elements
        while index < len(elements) and elements[index].tag in ("h1", "p"):
            self.header.append(elements[index])
            index += 1
        while index < len(elements):
            element = elements[index]
            if (
                element.tag == "h2"
                and index + 1 < len(elements)
                and elements[index + 1].tag == "table"
            ):
                table = elements[index + 1]
                self.statements.append(PrimaryStatement(element, table, self._parse_table(table)))
                index += 2
                continue
            if element.tag == "h2":
                self.notes_heading = element
                index += 1
                break
            index += 1
        current: PriorNote | None = None
        body: list[Element] = []
        while index < len(elements):
            element = elements[index]
            if element.tag == "h3":
                if current is not None:
                    self.notes.append(
                        PriorNote(current.number, current.title, current.heading, tuple(body))
                    )
                match = NOTE_HEADING.match(element.text)
                if not match:
                    raise ValueError(
                        f"{self.rel}: heading {element.text!r} is not 'Note N - Title'. "
                        f"Note numbering is read from the signed set, never guessed."
                    )
                current = PriorNote(int(match.group("number")), match.group("title"), element, ())
                body = []
            elif current is not None:
                body.append(element)
            index += 1
        if current is not None:
            self.notes.append(
                PriorNote(current.number, current.title, current.heading, tuple(body))
            )
        numbers = [n.number for n in self.notes]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"{self.rel}: notes are numbered {numbers}, which is not 1..n")

    def _parse_table(self, table: Element) -> tuple[StatementRow, ...]:
        rows: list[StatementRow] = []
        base = table.byte_start
        prefix_bytes = len(table.raw[:0].encode("utf-8"))  # 0; kept explicit for clarity
        del prefix_bytes
        section = ""
        for row_match in ROW.finditer(table.raw):
            row_html = row_match.group(1)
            row_offset = row_match.start(1)
            cells = list(CELL.finditer(row_html))
            texts = [strip_markup(c.group(2)).strip() for c in cells]
            if cells and cells[0].group(1) == "h":
                continue
            if len(cells) < 2:
                # A single spanning cell is a section header: "Non-current
                # liabilities". It is what tells the two "Borrowings" rows apart.
                if texts and texts[0]:
                    section = texts[0]
                    rows.append(
                        StatementRow(
                            caption=texts[0],
                            note_ref=None,
                            values=(),
                            cites=(),
                            is_total=False,
                            section=section,
                            is_section=True,
                        )
                    )
                continue
            caption = texts[0]
            note_ref: int | None = None
            if len(texts) > 1 and texts[1].isdigit():
                note_ref = int(texts[1])
            values: list[str] = []
            cites: list[Cite | None] = []
            for cell in cells[2:]:
                inner = cell.group(2)
                value = strip_markup(inner).strip()
                values.append(value)
                tokens = money_tokens(value)
                if len(tokens) == 1:
                    literal = tokens[0]
                    position = inner.find(literal)
                    if position >= 0:
                        start_char = row_offset + cell.start(2) + position
                        byte_start = base + len(table.raw[:start_char].encode("utf-8"))
                        cites.append(
                            Cite(
                                path=self.rel,
                                byte_start=byte_start,
                                byte_end=byte_start + len(literal.encode("utf-8")),
                                snippet=literal,
                                where=f"prior-year signed statements, row {caption!r}",
                            )
                        )
                        continue
                cites.append(None)
            rows.append(
                StatementRow(
                    caption=caption,
                    note_ref=note_ref,
                    values=tuple(values),
                    cites=tuple(cites),
                    is_total=caption.upper().startswith("TOTAL"),
                    section=section,
                )
            )
        return tuple(rows)

    # -- lookups -----------------------------------------------------------

    def note(self, number: int) -> PriorNote:
        for candidate in self.notes:
            if candidate.number == number:
                return candidate
        raise KeyError(f"{self.rel}: no note {number}")

    def statement_row(self, caption: str) -> tuple[PrimaryStatement, StatementRow] | None:
        for statement in self.statements:
            row = statement.row(caption)
            if row is not None:
                return statement, row
        return None

    def cite_in_note(self, number: int, literal: str, occurrence: int = 0) -> Cite:
        """Byte range of the `occurrence`-th `literal` inside note `number`'s body."""
        note = self.note(number)
        seen = 0
        for element in note.body:
            start = 0
            while True:
                position = element.raw.find(literal, start)
                if position < 0:
                    break
                if seen == occurrence:
                    byte_start = element.byte_start + len(element.raw[:position].encode("utf-8"))
                    return Cite(
                        path=self.rel,
                        byte_start=byte_start,
                        byte_end=byte_start + len(literal.encode("utf-8")),
                        snippet=literal,
                        where=f"prior-year signed statements, Note {number} ({note.title})",
                    )
                seen += 1
                start = position + len(literal)
        raise KeyError(
            f"{self.rel}: {literal!r} occurrence {occurrence} is not in Note {number}. "
            f"A comparative that is not in the signed set is not a comparative."
        )

    def note_references_in_prose(self) -> dict[int, list[int]]:
        """note number -> the note numbers its prose points at."""
        out: dict[int, list[int]] = {}
        for note in self.notes:
            hits = [int(m.group(1)) for e in note.body for m in NOTE_REFERENCE.finditer(e.text)]
            if hits:
                out[note.number] = hits
        return out
