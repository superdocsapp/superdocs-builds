"""Core data model for the exhibit indexer.

An ``Exhibit`` is one piece of evidence admitted into a filing. It carries the
source file, a human summary of what it *proves* (the cover-page text), and —
computed by the paginator — the page range it occupies inside the assembled
packet. The ``ExhibitSet`` is an ordered, numbered collection that knows how to
insert late (renumbering everything that depends on position) and to produce
the packet, the index, and the citation plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass
class Exhibit:
    """One exhibit in the set.

    ``number`` is the position in the exhibit set (1-based) and the label shown
    on its cover page and in the index. ``source`` is the original file path.
    ``proves`` is a one-sentence description of what the exhibit establishes,
    used verbatim on the cover page. ``page_start``/``page_end`` are filled in
    by the paginator and must always match the assembled packet.
    """

    number: int
    title: str                      # short label, e.g. "Passport — Reyansh Sharma"
    source: Path
    proves: str                     # "what it proves" cover-page line
    content: str = ""               # extracted text (used for pagination)
    page_start: int | None = None
    page_end: int | None = None

    @property
    def page_range(self) -> str:
        if self.page_start is None or self.page_end is None:
            return "—"
        if self.page_start == self.page_end:
            return f"p. {self.page_start}"
        return f"pp. {self.page_start}–{self.page_end}"


@dataclass
class Citation:
    """One in-brief citation to an exhibit.

    ``sentence`` is the brief sentence the citation attaches to; ``anchor`` is a
    short fragment used to relocate the sentence in the brief text after the AI
    edits it. ``exhibit_number`` is the exhibit being cited and ``rationale``
    explains the link for the reviewer.
    """

    sentence: str
    anchor: str
    exhibit_number: int
    rationale: str


class ExhibitSet:
    """An ordered, numbered collection of exhibits.

    All positional operations go through this class so that numbering, the
    cover pages, the index and any produced citations stay consistent: inserting
    one exhibit late renumbers every exhibit after it.
    """

    def __init__(self) -> None:
        self._items: list[Exhibit] = []

    # -- sequence protocol ----------------------------------------------------

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __getitem__(self, i):
        return self._items[i]

    # -- mutations -------------------------------------------------------------

    def add(self, *, source: Path, title: str, proves: str, content: str = "",
            after: int | None = None) -> Exhibit:
        """Append, or insert after the given 1-based exhibit number."""
        ex = Exhibit(number=0, title=title, source=source, proves=proves, content=content)
        if after is None:
            self._items.append(ex)
        else:
            self._items.insert(after, ex)
        self._renumber()
        return ex

    def remove(self, number: int) -> None:
        """Remove the exhibit with the given 1-based number."""
        for i, ex in enumerate(self._items):
            if ex.number == number:
                del self._items[i]
                self._renumber()
                return
        raise KeyError(f"no exhibit {number}")

    def _renumber(self) -> None:
        for i, ex in enumerate(self._items, start=1):
            ex.number = i

    # -- page layout (computed, not stored) ------------------------------------

    def paginated(self, lines_per_page: int = 40) -> "PaginatedPacket":
        """Assign real page numbers to every exhibit inside one continuous packet.

        Returns a ``PaginatedPacket`` describing the layout; the same layout is
        what :meth:`render_packet` renders, so index ranges and the export are
        always in agreement.
        """
        from .paging import paginate_set
        return paginate_set(self, lines_per_page=lines_per_page)

    # -- output builders ---------------------------------------------------------

    def render_covers(self) -> list[str]:
        """One numbered cover page (HTML) per exhibit."""
        from .covers import render_cover
        return [render_cover(ex) for ex in self._items]

    def render_index(self, packet: "PaginatedPacket | None" = None) -> str:
        """The exhibit index (HTML) with page ranges matching the packet."""
        from .index import render_index
        return render_index(self, packet)

    def render_packet(self, lines_per_page: int = 40) -> str:
        """The whole filing as one paginated HTML document."""
        from .paging import render_packet
        return render_packet(self, lines_per_page=lines_per_page)

    def citation_plan(self, brief: str) -> list[Citation]:
        """Find where the brief relies on each exhibit; propose citations."""
        from .citations import plan_citations
        return plan_citations(self, brief)

    # -- helpers -----------------------------------------------------------------

    def by_number(self, number: int) -> Exhibit:
        for ex in self._items:
            if ex.number == number:
                return ex
        raise KeyError(f"no exhibit {number}")

    def as_list(self) -> list[Exhibit]:
        return [replace(ex) for ex in self._items]


@dataclass
class PaginatedPacket:
    """The layout of one assembled packet.

    ``cover_pages`` is the number of pages the packet's own front cover and the
    index occupy before any exhibit starts; each exhibit's ``page_start`` is set
    on the exhibit objects themselves.
    """

    front_matter_pages: int
    total_pages: int
    set: ExhibitSet
