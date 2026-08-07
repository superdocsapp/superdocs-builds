"""Pagination: the page ranges in the index MUST match the assembled packet.

This is the task's strong requirement. The invariant is tested by rendering the
packet and asserting (a) every exhibit's advertised page range falls inside the
rendered page count, and (b) the front matter the index occupies is exactly what
``index_page_count`` promised.
"""

from __future__ import annotations

from pathlib import Path

from exhibit import paginate_set, render_packet
from exhibit.index import render_index
from exhibit.model import ExhibitSet
from exhibit.paging import INDEX_ROWS_PER_PAGE, index_page_count


def _set_of(n: int, lines_each: int = 3) -> ExhibitSet:
    set_ = ExhibitSet()
    for i in range(1, n + 1):
        set_.add(
            source=Path(f"doc-{i}.txt"),
            title=f"Document {i}",
            proves=f"Evidences topic {i}.",
            content="\n".join(f"line {j} of document {i}" for j in range(lines_each)),
        )
    return set_


def test_index_page_count_known_values():
    assert index_page_count(0) == 1
    assert index_page_count(1) == 1
    assert index_page_count(INDEX_ROWS_PER_PAGE) == 1
    assert index_page_count(INDEX_ROWS_PER_PAGE + 1) == 2
    assert index_page_count(2 * INDEX_ROWS_PER_PAGE) == 2
    assert index_page_count(2 * INDEX_ROWS_PER_PAGE + 1) == 3


def test_packet_front_matter_matches_index_page_count():
    set_ = _set_of(5)
    packet = paginate_set(set_)
    # packet cover (1) + index pages
    assert packet.front_matter_pages == 1 + index_page_count(5)
    # index occupies exactly the promised pages in the rendered packet
    html = render_packet(set_)
    assert html.count('class="page index"') == index_page_count(5)


def test_exhibit_ranges_match_rendered_packet():
    """The strong requirement: index page ranges equal the pages the packet
    actually occupies. Every exhibit's range must fall within the rendered page
    blocks, and consecutive exhibits must be adjacent with no gaps."""
    set_ = _set_of(8, lines_each=5)
    packet = paginate_set(set_)
    html = render_packet(set_)
    total_pages = html.count('class="page ')

    assert packet.total_pages == total_pages, "packet.total_pages must equal rendered pages"
    prev_end = packet.front_matter_pages
    for ex in set_:
        assert ex.page_start == prev_end + 1, "exhibits must start on fresh pages, no gaps"
        assert ex.page_end >= ex.page_start
        assert ex.page_end <= total_pages, "index range exceeds the rendered packet"
        prev_end = ex.page_end

    # the rendered index must advertise exactly the same ranges
    index_html = render_index(set_)
    for ex in set_:
        assert ex.page_range in index_html, f"index omits or misstates {ex.page_range}"


def test_late_insertion_repaginates_consistently():
    set_ = _set_of(3)
    paginate_set(set_)
    before = [(ex.number, ex.page_start, ex.page_end) for ex in set_]

    set_.add(source=Path("new.pdf"), title="New Evidence",
             proves="Evidences the new matter.", content="late\ninserted\ncontent",
             after=1)
    packet = paginate_set(set_)

    assert [ex.number for ex in set_] == [1, 2, 3, 4]
    # the exhibit after the inserted one starts exactly after the new one's span
    new = set_.by_number(2)
    following = set_.by_number(3)
    assert following.page_start == new.page_start + (new.page_end - new.page_start + 1)
    # and the tail stays contiguous to the end
    for a, b in zip(set_, set_[1:]):
        assert b.page_start == a.page_end + 1
    assert packet.total_pages == 1 + index_page_count(4) + sum(
        1 + _content_pages_of(ex) for ex in set_
    )


def test_render_packet_is_one_continuous_document():
    set_ = _set_of(4)
    html = render_packet(set_)
    assert html.count("<!doctype html>") == 1
    assert html.count('<section class="page cover">') == 1
    assert html.count('<section class="page exhibit-cover"') == 4


def _content_pages_of(ex) -> int:
    return max(1, -(-len(ex.content.splitlines()) // 40))
