"""The archive: what it should contain, computed from what it does contain.

WHY THIS FILE EXISTS (it is the most important design decision in build #1).

The first version asked SuperDocs to *insert a row at the top of the archive
table*. Over five weeks that produced three different failures: rows appended
at the bottom instead of the top, the header row duplicated into the table
body, and one week's row silently dropped. Three symptoms, one cause -
"insert at position X" is a positional instruction, and positional
instructions are the fragile kind.

The fix is to stop giving positional instructions. Every week the runner reads
the archive rows the document currently holds, computes the exact list of rows
it should hold afterwards, and asks for **that list**. Position stops being
something the model has to get right and becomes something the enumeration
already encodes.

What is still delegated to the model is the part only a model can do: the prose
inside the one new row (a summary of what the standing sections currently say)
and inside a rollup row (a summary of the four rows being folded). Those cells
are marked AUTHOR in the plan; every other cell is carried across verbatim.

Facts are transported. Prose is generated. The archive is where that line is
drawn most visibly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from superdocs_kit.docdiff import section_html, table_rows

from .document import ARCHIVE_MAX_DETAIL_ROWS, ARCHIVE_ROLLUP_SIZE

AUTHOR = "<AUTHOR>"
_WEEK_RE = re.compile(r"^\s*Week\s+(\d+)\s*$", re.I)
_ROLLUP_RE = re.compile(r"^\s*Weeks\s+(\d+)\s*[-–]\s*(\d+)", re.I)


@dataclass
class ArchiveRow:
    label: str
    dates: str
    shipped: str
    risks: str
    source_rows: list[list[str]] = field(default_factory=list)

    @property
    def needs_authoring(self) -> bool:
        return AUTHOR in (self.shipped, self.risks)

    @property
    def covered_weeks(self) -> set[int]:
        m = _WEEK_RE.match(self.label)
        if m:
            return {int(m.group(1))}
        m = _ROLLUP_RE.match(self.label)
        if m:
            return set(range(int(m.group(1)), int(m.group(2)) + 1))
        return set()


def parse_existing(html: str) -> list[ArchiveRow]:
    """The archive rows the document actually holds right now.

    Anything that is not a recognisable week row - the seed placeholder, a
    header row the model accidentally copied into the body - is dropped here
    rather than propagated. Repairing the archive is free; it happens as a
    side effect of restating it.
    """
    rows: list[ArchiveRow] = []
    for cells in table_rows(section_html(html, "Archive"))[1:]:
        if len(cells) < 4:
            continue
        label = cells[0].strip()
        if not (_WEEK_RE.match(label) or _ROLLUP_RE.match(label)):
            continue
        rows.append(ArchiveRow(label, cells[1].strip(), cells[2].strip(), cells[3].strip()))
    return rows


def plan_rows(before_html: str, prev_week: dict) -> tuple[list[ArchiveRow], ArchiveRow | None]:
    """The exact archive body for this week, newest first.

    Returns (rows, rollup_row_or_None).
    """
    existing = parse_existing(before_html)
    seen: set[int] = set()
    deduped: list[ArchiveRow] = []
    for row in existing:                      # keep the newest copy of a week
        if row.covered_weeks & seen:
            continue
        seen |= row.covered_weeks
        deduped.append(row)

    new_row = ArchiveRow(f"Week {prev_week['week']}", prev_week["dates"], AUTHOR, AUTHOR)
    rows = [new_row] + deduped

    detail = [r for r in rows if _WEEK_RE.match(r.label)]
    rollup_row: ArchiveRow | None = None
    if len(detail) > ARCHIVE_MAX_DETAIL_ROWS:
        oldest = detail[-ARCHIVE_ROLLUP_SIZE:]
        weeks = sorted(w for r in oldest for w in r.covered_weeks)
        rollup_row = ArchiveRow(
            f"Weeks {weeks[0]}-{weeks[-1]} (rolled up)",
            f"{oldest[-1].dates.split(' to ')[0]} to {oldest[0].dates.split(' to ')[-1]}",
            AUTHOR, AUTHOR,
            source_rows=[[r.label, r.dates, r.shipped, r.risks] for r in oldest],
        )
        keep = [r for r in rows if r not in oldest]
        idx = len(keep) - len([r for r in keep if _ROLLUP_RE.match(r.label)])
        rows = keep[:idx] + [rollup_row] + keep[idx:]

    return rows, rollup_row


def render_instruction_block(rows: list[ArchiveRow], rollup: ArchiveRow | None) -> str:
    """Enumerate the desired archive body as an instruction.

    Deliberately terse. The first version restated every existing row's full
    text, and by week 6 the archive block alone was most of a 5 KB instruction -
    at which point the model reliably did the archive and dropped the four steps
    after it. Naming the rows in order and saying "leave the others exactly as
    they are" carries the same information in a tenth of the characters, and the
    ordering is still fully determined.
    """
    lines = [
        "  The rows, top to bottom, must be exactly: "
        + ", ".join(f"'{r.label}'" for r in rows) + ".",
        "  The first cell of each of those rows must read exactly as quoted, "
        "INCLUDING the word 'Week' - write 'Week 3', never '3'. The column is "
        "headed 'Week'; that heading is not a substitute for the label.",
    ]
    for row in rows:
        if row is rollup:
            src = ", ".join(f"'{c[0]}'" for c in row.source_rows)
            lines.append(
                f"  Row '{row.label}' is NEW and REPLACES the rows {src}. Its Dates "
                f"cell is '{row.dates}'. Its Shipped cell is one sentence of at most "
                f"25 words summarising those {len(row.source_rows)} rows together. Its "
                f"Risks carried cell is at most 10 words. Delete those rows."
            )
        elif row.needs_authoring:
            lines.append(
                f"  Row '{row.label}' is NEW. Its Dates cell is '{row.dates}'. Its "
                f"Shipped cell is your own summary, at most 20 words, of the bullets "
                f"currently under 'What changed'. Its Risks carried cell is your own "
                f"summary, at most 15 words, of the rows currently in the 'What is at "
                f"risk' table."
            )
    lines.append(
        "  Every other row keeps its existing cell contents exactly as they are - "
        "do not rewrite, reword or re-summarise them."
    )
    return "\n".join(lines)


def expected_coverage(week: int) -> set[int]:
    """Which weeks the archive must account for after week N's edit."""
    return set(range(1, week))
