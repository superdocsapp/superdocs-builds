"""The exhibit index: the map of the packet.

One table row per exhibit: its number, its title, what it proves, and — the
critical part — the page range it occupies in the *assembled packet*. Rows are
split across index pages (``INDEX_ROWS_PER_PAGE`` per page), which is the exact
page count ``paging.index_page_count`` promised during pagination, so the index
pages and the exhibit page numbers always line up.
"""

from __future__ import annotations

import html as _html

from .model import ExhibitSet
from .paging import INDEX_ROWS_PER_PAGE, index_page_count


def render_index(set_: ExhibitSet, packet=None) -> str:
    """Render the index. ``packet`` may be a ``PaginatedPacket`` (or ``None`` to
    fall back to whatever page numbers are already assigned)."""
    pages: list[str] = []
    rows = list(set_)
    for page_no in range(index_page_count(len(rows))):
        slice_rows = rows[page_no * INDEX_ROWS_PER_PAGE : (page_no + 1) * INDEX_ROWS_PER_PAGE]
        body = "\n".join(_entry_row(ex) for ex in slice_rows)
        pages.append(f'<section class="page index">{body}</section>')
    return "\n".join(pages)


def _entry_row(ex) -> str:
    rng = ex.page_range if ex.page_start is not None else "—"
    return (
        '<div class="index-entry">'
        f'<span class="no">Exhibit {ex.number}</span>'
        f'<span class="t">{_html.escape(ex.title)}</span>'
        f'<span class="p">{rng}</span>'
        "</div>"
    )
