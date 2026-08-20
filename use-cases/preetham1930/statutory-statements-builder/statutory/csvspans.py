"""An RFC 4180 scanner that keeps byte positions.

`csv.reader` yields values and throws positions away, and the positions are the
whole point: a figure we write into the statements has to name the byte range it
came from. Rebuilt here rather than imported (Decision 31); the idea is copied
from `system/ingest`, the code is not.

Assumption: the corpus CSVs are UTF-8 with `\\n` or `\\r\\n` line endings and no
embedded newlines inside quoted fields. Both hold across all three corpus CSVs
and `.gitattributes` pins the endings; a file that breaks it raises rather than
mis-parsing, because a silently wrong byte offset is worse than a loud stop.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    value: str
    byte_start: int
    byte_end: int

    @property
    def text(self) -> str:
        return self.value.strip()


def parse_csv(raw: bytes) -> list[list[Cell]]:
    """Rows of cells. `byte_start`/`byte_end` span the field's *value* bytes.

    For a quoted field the span is the bytes inside the quotes, so a citation
    reads back as the value rather than as the value plus its punctuation.
    """
    rows: list[list[Cell]] = []
    row: list[Cell] = []
    i = 0
    n = len(raw)
    while i <= n:
        if i == n:
            if row or (rows and raw.endswith(b"\n")):
                pass
            break
        byte = raw[i : i + 1]
        if byte == b'"':
            start = i + 1
            j = start
            chunks: list[bytes] = []
            while j < n:
                if raw[j : j + 1] == b'"':
                    if raw[j + 1 : j + 2] == b'"':
                        chunks.append(b'"')
                        j += 2
                        continue
                    break
                chunks.append(raw[j : j + 1])
                j += 1
            if j >= n:
                raise ValueError(f"unterminated quoted field starting at byte {i}")
            row.append(Cell(b"".join(chunks).decode("utf-8"), start, j))
            i = j + 1
            # A quoted field must be followed by a delimiter, a newline or EOF.
            if i < n and raw[i : i + 1] not in (b",", b"\r", b"\n"):
                raise ValueError(f"stray bytes after a quoted field at byte {i}")
        else:
            j = i
            while j < n and raw[j : j + 1] not in (b",", b"\r", b"\n"):
                j += 1
            row.append(Cell(raw[i:j].decode("utf-8"), i, j))
            i = j
        if i < n and raw[i : i + 1] == b",":
            i += 1
            continue
        if i < n and raw[i : i + 1] == b"\r":
            i += 1
        if i < n and raw[i : i + 1] == b"\n":
            i += 1
        rows.append(row)
        row = []
        if i >= n:
            break
    if row:
        rows.append(row)
    return [r for r in rows if r and not (len(r) == 1 and r[0].value == "")]


def as_records(rows: list[list[Cell]]) -> tuple[list[str], list[dict[str, Cell]]]:
    """Header row plus one dict per data row, keyed by column name."""
    if not rows:
        raise ValueError("empty CSV: no header row")
    header = [c.text for c in rows[0]]
    records = []
    for row in rows[1:]:
        if len(row) != len(header):
            raise ValueError(
                f"row has {len(row)} field(s) but the header has {len(header)}: "
                f"{[c.text for c in row]}"
            )
        records.append(dict(zip(header, row, strict=True)))
    return header, records
