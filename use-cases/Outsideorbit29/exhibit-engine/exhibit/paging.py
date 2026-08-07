"""Deterministic pagination for the assembled packet.

The whole point of an exhibit index is that its page ranges tell you where to
find each exhibit *in the finished filing*. So pagination has a hard invariant:

    the page ranges printed in the index MUST equal the pages the assembled
    packet actually occupies.

We keep that invariant by construction: ``paginate_set`` is the single place
page numbers are assigned, and ``render_packet`` renders exactly the same
layout it assigned — one HTML page block per page, a page-break before each
exhibit cover, so the rendered file and the index can never disagree.

Layout of the packet (in order):
    1. packet cover page                       (1 page)
    2. exhibit index                           (1+ pages)
    3. for each exhibit: its cover page + its content pages

Every exhibit starts on a fresh page. Content pagination is line-based and
deterministic (``LINES_PER_PAGE`` lines per page), so the same text always
produces the same page range regardless of machine.
"""

from __future__ import annotations

import html as _html

from .model import ExhibitSet, PaginatedPacket

# Lines of exhibit content that fit on one page. Deterministic by design.
LINES_PER_PAGE = 40

# Index rows per page in the packet's front matter.
INDEX_ROWS_PER_PAGE = 20


def index_page_count(num_exhibits: int) -> int:
    """Pages the index occupies given the number of exhibits.

    This is the *single* source of truth for how many pages the index takes, so
    pagination (assigning page numbers) and rendering (laying the index down)
    can never disagree.
    """
    return max(1, -(-num_exhibits // INDEX_ROWS_PER_PAGE))


def _content_pages(exhibit) -> int:
    """How many content pages one exhibit occupies (cover page excluded)."""
    lines = exhibit.content.splitlines() if exhibit.content else []
    if not lines:
        return 1  # even an empty exhibit takes a page
    return max(1, -(-len(lines) // LINES_PER_PAGE))


def paginate_set(set_: ExhibitSet, lines_per_page: int = LINES_PER_PAGE) -> PaginatedPacket:
    """Assign ``page_start``/``page_end`` to every exhibit in the set.

    The packet is paginated as a continuous document. We render the index first
    (its length depends only on the number of exhibits), count the front matter,
    then lay exhibits down one after another — cover page first, content after.
    """
    if lines_per_page != LINES_PER_PAGE:
        # Only the default pagination is guaranteed to match the rendered
        # packet; a custom value is allowed for testing the *model*.
        return _paginate_custom(set_, lines_per_page)

    front_matter = 1 + index_page_count(len(set_))  # packet cover + index

    cursor = front_matter + 1
    for ex in set_:
        ex.page_start = cursor
        ex.page_end = cursor + _content_pages(ex)
        cursor = ex.page_end + 1

    total = cursor - 1
    return PaginatedPacket(front_matter_pages=front_matter, total_pages=total, set=set_)


def _paginate_custom(set_: ExhibitSet, lines_per_page: int) -> PaginatedPacket:
    front_matter = 1
    cursor = front_matter + 1
    for ex in set_:
        ex.page_start = cursor
        ex.page_end = cursor + max(1, -(-max(1, len(ex.content.splitlines())) // lines_per_page))
        cursor = ex.page_end + 1
    return PaginatedPacket(front_matter_pages=front_matter, total_pages=cursor - 1, set=set_)


# --------------------------------------------------------------------------- rendering


def render_packet(set_: ExhibitSet, lines_per_page: int = LINES_PER_PAGE) -> str:
    """Render the whole filing as one paginated HTML document.

    Each page is a ``<section class="page">``; the first page of every exhibit is
    its numbered cover page. A ``page-break-before`` on each exhibit cover keeps
    the printed file aligned with the page numbers the index advertises.
    """
    assert lines_per_page == LINES_PER_PAGE, "render_packet only supports default pagination"
    paginate_set(set_)

    from .covers import render_cover, render_packet_cover  # local import avoids a cycle

    blocks: list[str] = []
    blocks.append(render_packet_cover(set_))
    blocks.append(_index_markup(set_))
    for ex in set_:
        blocks.append(render_cover(ex))
        blocks.extend(_content_pages_html(ex))
    return _html_document("".join(blocks))


def _index_markup(set_: ExhibitSet) -> str:
    from .index import render_index  # local import avoids a cycle
    return render_index(set_)


def _content_pages_html(exhibit) -> list[str]:
    lines = exhibit.content.splitlines() if exhibit.content else [""]
    pages: list[str] = []
    for i in range(0, len(lines), LINES_PER_PAGE):
        chunk = "\n".join(lines[i : i + LINES_PER_PAGE])
        body = _html.escape(chunk).replace("\n", "<br/>")
        pages.append(f'<section class="page exhibit-page">{body}</section>')
    return pages


# --------------------------------------------------------------------------- shared markup helpers


def _html_page_count(html: str) -> int:
    """Count index pages in markup; kept for symmetry (front matter uses the
    shared ``index_page_count`` so pagination and rendering agree by design)."""
    return max(1, html.count('class="page index"'))


def _html_document(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
  body {{ font-family: Georgia, serif; margin: 0; }}
  section.page {{ width: 8.5in; min-height: 11in; padding: 1in; box-sizing: border-box;
                  page-break-after: always; }}
  .cover {{ text-align: center; }}
  .packet-title {{ font-size: 26pt; margin-top: 3in; }}
  .packet-count {{ font-size: 14pt; margin-top: 8pt; color: #444; }}
  .exhibit-cover {{ text-align: center; }}
  .exhibit-no {{ font-size: 12pt; letter-spacing: .2em; color: #666; }}
  .exhibit-title {{ font-size: 22pt; margin-top: 1.5in; }}
  .exhibit-proves {{ font-size: 13pt; margin: 1in auto; width: 5.5in; line-height: 1.5; }}
  .exhibit-page {{ font-size: 11pt; line-height: 1.4; }}
  table.index {{ width: 100%; border-collapse: collapse; font-size: 11pt; }}
  table.index th, table.index td {{ border-bottom: 1px solid #999; padding: 6pt 8pt; text-align: left; }}
</style></head><body>
{body}
</body></html>"""
