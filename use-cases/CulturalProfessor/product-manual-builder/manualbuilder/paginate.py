"""Where each block lands, so a translation can be shown not to move it.

`localize.py` proves a translation has the same *shape*: the same headings, the
same figures, in the same order. That is necessary and it is not sufficient. Two
documents with an identical outline still paginate differently the moment one of
them is twelve per cent longer, which is what German is, and the failure that
produces is the one that actually costs money: step six is on page seven with
its diagram in English and on page eight without it in German, and nobody sees
it until the print run is boxed.

So this module lays both documents out and compares where things landed.

Two mechanisms, and the order matters.

**Most page breaks are declared, not discovered.** Every section heading and
every setup step carries `starts_page`, so which page a step opens on falls out
of the spec's structure rather than out of how long the preceding sentences
happen to be. A translation inherits those breaks because it inherits the
blocks. That is what makes stability the default rather than the lucky case.

**What is left is measured.** Inside a page, content still flows, and a longer
translation can still push a table onto an extra page and shift everything after
it. `compare` finds that and names the block that moved.

What this is not: a renderer. The numbers below are a layout *model* -- lines of
a fixed width on a page of a fixed height, calibrated to A4 at 11pt with the
figures at a third of the text column. It cannot tell you the true page count of
a PDF nobody has produced yet. What it can tell you, and what is actually being
claimed, is relative: the same model applied to both languages puts every block
on the same page. A model wrong in the same direction for both is still a valid
comparison, and the one place to change if the house style changes is `Box`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from manualbuilder.projections import Block


class PaginationError(ValueError):
    """A localised document does not paginate like its source."""


@dataclass(frozen=True)
class Box:
    """The page, in lines. One place to change if the house style changes."""
    lines_per_page: int = 46
    chars_per_line: int = 88
    figure_lines: int = 16       # a diagram at a third of the text column
    heading_lines: dict[str, int] = field(
        default_factory=lambda: {"h1": 5, "h2": 4, "h3": 3})
    table_header_lines: int = 2
    space_after_paragraph: int = 1

    def wrapped(self, text: str) -> int:
        return max(1, math.ceil(len(text) / self.chars_per_line))


#: The manual: A4, printed one side per page.
PAGE = Box()

#: The quick-start card: an A5 concertina panel at 9pt, about a third the height
#: of the manual page and a third narrower. The card is not a small manual and
#: it is not laid out like one -- the unit that has to hold is the panel between
#: two creases, and it is a physical fact about the printed card rather than
#: something a translation gets to negotiate.
#: 28 lines rather than 26: at 26 the German troubleshooting panel comes to
#: exactly 26, which passes and is not a card anyone should print. The number
#: that matters is the headroom the tightest panel leaves the next translation,
#: and `check` prints it for every locale so it is a fact rather than a hope.
PANEL = Box(lines_per_page=28, chars_per_line=58, figure_lines=9,
            heading_lines={"h1": 3, "h2": 2, "h3": 2})


@dataclass(frozen=True)
class Placement:
    """One block, or part of one, on one page."""
    block_id: str
    page: int
    lines: int
    rows: tuple[int, int] | None = None   # for a table split across pages

    @property
    def is_partial(self) -> bool:
        return self.rows is not None


@dataclass(frozen=True)
class Layout:
    placements: tuple[Placement, ...]
    used: tuple[int, ...]          # lines used, per page
    box: Box

    @property
    def pages(self) -> int:
        return len(self.used)

    def span(self, block_id: str) -> tuple[int, int]:
        """The first and last page a block appears on."""
        pages = [p.page for p in self.placements if p.block_id == block_id]
        if not pages:
            raise KeyError(block_id)
        return min(pages), max(pages)

    def spans(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for placement in self.placements:
            first, last = out.get(placement.block_id, (placement.page, placement.page))
            out[placement.block_id] = (min(first, placement.page),
                                       max(last, placement.page))
        return out

    def fill(self) -> list[float]:
        return [used / self.box.lines_per_page for used in self.used]

    def tightest(self) -> tuple[int, float]:
        """The fullest page, and how full. Headroom is what a translation eats."""
        fills = self.fill()
        page = max(range(len(fills)), key=lambda i: fills[i])
        return page + 1, fills[page]

    def overflows(self) -> list[tuple[str, int]]:
        """Blocks too tall for a page even alone, with the excess in lines.

        Reported rather than raised: a single unsplittable thing bigger than the
        page is a real document to fix, not a crash, and the caller decides.
        """
        out: list[tuple[str, int]] = []
        for index, used in enumerate(self.used):
            if used > self.box.lines_per_page:
                on_page = [p.block_id for p in self.placements if p.page == index + 1]
                out.append((on_page[0] if on_page else f"page {index + 1}",
                            used - self.box.lines_per_page))
        return out


# ------------------------------------------------------------- measuring --

def height(block: Block, box: Box) -> int:
    if block.kind in box.heading_lines:
        return box.heading_lines[block.kind] + box.wrapped(block.text) - 1
    if block.kind == "figure":
        return box.figure_lines + box.wrapped(block.text)
    if block.kind == "table":
        return box.table_header_lines + sum(box.wrapped(row) for row in block.rows)
    return box.wrapped(block.text) + box.space_after_paragraph


def _row_heights(block: Block, box: Box) -> list[int]:
    return [box.wrapped(row) for row in block.rows]


def _groups(blocks: list[Block]) -> list[list[Block]]:
    """Maximal runs that must not be split across a page.

    A heading and the thing it introduces; a step's heading, its diagram and its
    instruction. `keep_with_next` on every member but the last is what declares
    the run, and it is set where the document is built rather than guessed here.
    """
    out: list[list[Block]] = []
    current: list[Block] = []
    for block in blocks:
        current.append(block)
        if not block.keep_with_next:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


# --------------------------------------------------------------- laying out --

def paginate(blocks: list[Block], box: Box | None = None) -> Layout:
    box = box or Box()
    placements: list[Placement] = []
    used: list[int] = [0]

    def page() -> int:
        return len(used)

    def remaining() -> int:
        return box.lines_per_page - used[-1]

    def new_page() -> None:
        used.append(0)

    for group in _groups(blocks):
        if group[0].starts_page and used[-1] > 0:
            new_page()

        needed = sum(height(block, box) for block in group)

        # It fits on a page, just not on what is left of this one: move it whole.
        if needed > remaining() and used[-1] > 0 and needed <= box.lines_per_page:
            new_page()

        # Still too big, which means it is bigger than a page. A table is the
        # one thing that may be cut mid-way, because that is what a table does
        # on paper: the rows keep going overleaf. Anything else is placed and
        # reported by `overflows` rather than silently squeezed.
        if needed > remaining() and _splittable(group, box, remaining()):
            placements += _split(group, box, used, page)
            continue

        for block in group:
            lines = height(block, box)
            placements.append(Placement(block.id, page(), lines))
            used[-1] += lines

    return Layout(tuple(placements), tuple(used), box)


def _splittable(group: list[Block], box: Box, space: int) -> bool:
    """Only a group ending in a table, whose head plus one row already fits."""
    if group[-1].kind != "table" or not group[-1].rows:
        return False
    head = sum(height(block, box) for block in group[:-1])
    rows = _row_heights(group[-1], box)
    return head + box.table_header_lines + rows[0] <= space


def _split(group: list[Block], box: Box, used: list[int], page) -> list[Placement]:
    placements: list[Placement] = []
    for block in group[:-1]:
        lines = height(block, box)
        placements.append(Placement(block.id, page(), lines))
        used[-1] += lines

    table = group[-1]
    rows = _row_heights(table, box)
    index = 0
    while index < len(rows):
        # The header repeats on every page the table continues onto, which is
        # both what a printed manual does and why a split costs lines.
        here = box.table_header_lines
        used[-1] += here
        start = index
        while index < len(rows) and used[-1] + rows[index] <= box.lines_per_page:
            used[-1] += rows[index]
            here += rows[index]
            index += 1
        if index == start:
            # A single row taller than the page. It cannot be made to fit, so it
            # is placed and reported by `overflows` -- the alternative is
            # looping forever looking for a page big enough.
            used[-1] += rows[index]
            here += rows[index]
            index += 1
        placements.append(Placement(table.id, page(), here, rows=(start, index)))
        if index < len(rows):
            used.append(0)
    return placements


# ------------------------------------------------------------- comparing --

@dataclass(frozen=True)
class Shift:
    block_id: str
    expected: tuple[int, int]
    found: tuple[int, int]

    def __str__(self) -> str:
        return (f"{self.block_id} was on {_pages(self.expected)}, "
                f"is on {_pages(self.found)}")


def _pages(span: tuple[int, int]) -> str:
    first, last = span
    return f"page {first}" if first == last else f"pages {first}–{last}"


def compare(source: Layout, localised: Layout) -> list[Shift]:
    """Every block that landed on a different page than it does in the source."""
    want, got = source.spans(), localised.spans()
    shifts: list[Shift] = []
    for block_id, span in want.items():
        if block_id not in got:
            shifts.append(Shift(block_id, span, (0, 0)))
        elif got[block_id] != span:
            shifts.append(Shift(block_id, span, got[block_id]))
    for block_id in got:
        if block_id not in want:
            shifts.append(Shift(block_id, (0, 0), got[block_id]))
    return shifts


def assert_same_pagination(source: Layout, localised: Layout,
                           language: str, document: str = "manual") -> None:
    """Refuse a translation that would print differently from its source.

    The message names the blocks, not a page count, because "4 pages became 5"
    sends whoever reads it looking through the whole document, and
    "step:power:figure moved from page 7 to page 8" sends them to the sentence
    above it.
    """
    # Overflow first, because it is the failure the declared breaks leave
    # behind. With every step opening its own page, a translation that runs long
    # has nothing left to push: it fills its page past the bottom instead, and a
    # comparison of page numbers alone would call that stable and be wrong.
    overflows = localised.overflows()
    if overflows:
        raise PaginationError(
            f"the {language} {document} paginates on the same pages as the "
            f"source and does not fit on them:\n  - "
            + "\n  - ".join(
                f"{block_id} overruns its page by {excess} line"
                f"{'' if excess == 1 else 's'}" for block_id, excess in overflows[:5])
        )

    shifts = compare(source, localised)
    if not shifts:
        return
    shown = shifts[:5]
    more = ("" if len(shifts) <= len(shown)
            else f"\n  ... and {len(shifts) - len(shown)} more")
    raise PaginationError(
        f"the {language} {document} does not paginate like the source "
        f"({source.pages} pages became {localised.pages}); the translation is "
        f"longer than the layout has room for:\n  - "
        + "\n  - ".join(str(shift) for shift in shown) + more
    )


__all__ = ["Box", "Layout", "Placement", "Shift", "PaginationError", "paginate",
           "compare", "assert_same_pagination", "height"]
