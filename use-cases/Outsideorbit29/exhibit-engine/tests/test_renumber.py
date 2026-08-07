"""Late insertion renumbers EVERYTHING that depends on position — covers,
index, page ranges and in-brief citations — together and consistently.

These are the task's strong requirements, so they get dedicated tests.
"""

from __future__ import annotations

from pathlib import Path

from exhibit.covers import render_cover
from exhibit.index import render_index
from exhibit import proposals
from exhibit.paging import paginate_set


def _simple_items():
    from exhibit.order import EvidenceItem

    return [
        EvidenceItem(source="passport.pdf", text="passport nationality birth identity visa"),
        EvidenceItem(source="marriage.pdf", text="marriage certificate wedding married couple"),
        EvidenceItem(source="lease.pdf", text="lease residence home together joint"),
        EvidenceItem(source="bank.pdf", text="bank statements account transfer deposit"),
    ]


BRIEF = (
    "The applicant's identity is established by his passport. The marriage is "
    "shown by the marriage certificate. The couple lives together under a joint "
    "lease. Their finances are intermingled through joint bank accounts."
)


def test_late_insert_renumbers_covers_and_index():
    prop = proposals.propose(BRIEF, _simple_items())
    before = [ex.number for ex in prop.set]

    # Insert a brand-new exhibit after position 2.
    prop.set.add(source=Path("photo.pdf"), title="Wedding Photos",
                 proves="Evidences the wedding ceremony.",
                 content="wedding ceremony photographs bride groom", after=2)
    proposals.replan(prop.set, BRIEF)

    assert [ex.number for ex in prop.set] == [1, 2, 3, 4, 5]
    # Every cover page renders with the renumbered label.
    for ex in prop.set:
        assert f"Exhibit {ex.number}" in render_cover(ex)
    # The index reflects the new numbers and the same page ranges as the set.
    index_html = render_index(prop.set)
    for ex in prop.set:
        assert f"Exhibit {ex.number}" in index_html
        assert ex.page_range in index_html


def test_late_insert_renumbers_in_brief_citations():
    prop = proposals.propose(BRIEF, _simple_items())
    # Record which exhibit each citation pointed at before the insertion.
    old_anchor_to_exhibit = {c.anchor: c.exhibit_number for c in prop.citations}

    prop.set.add(source=Path("photo.pdf"), title="Wedding Photos",
                 proves="Evidences the wedding ceremony.",
                 content="wedding ceremony photographs bride groom", after=1)
    prop.repropose(BRIEF)

    # The citation that used to point at the old exhibit 3 (lease) now points at
    # the renumbered exhibit 4, because the lease moved down one slot.
    lease_cit = next(c for c in prop.citations if "joint lease" in c.anchor)
    assert lease_cit.exhibit_number == 4
    # Every citation references a real exhibit that still exists.
    for c in prop.citations:
        assert 1 <= c.exhibit_number <= len(prop.set)
    # Every exhibit is cited exactly once, and no anchor hosts more citations
    # than the co-citation limit (two exhibits can genuinely rely on one
    # sentence, e.g. "...joint bank accounts and a joint tax return...").
    from collections import Counter

    from exhibit.citations import MAX_CITES_PER_SENTENCE

    assert len({c.exhibit_number for c in prop.citations}) == len(prop.citations)
    anchors = [c.anchor for c in prop.citations]
    assert max(Counter(anchors).values()) <= MAX_CITES_PER_SENTENCE


def test_citation_numbers_are_contiguous_after_insert():
    prop = proposals.propose(BRIEF, _simple_items())
    prop.set.add(source=Path("photo.pdf"), title="Wedding Photos",
                 proves="Evidences the wedding ceremony.",
                 content="wedding ceremony photographs", after=0)
    fresh = proposals.replan(prop.set, BRIEF)
    numbers = sorted(c.exhibit_number for c in fresh.citations)
    assert numbers == list(range(1, len(prop.set) + 1))


def test_remove_renumbers_everything():
    prop = proposals.propose(BRIEF, _simple_items())
    prop.set.remove(3)
    prop.repropose(BRIEF)
    assert [ex.number for ex in prop.set] == [1, 2, 3]
    for c in prop.citations:
        assert c.exhibit_number in {1, 2, 3}
    for ex in prop.set:
        assert f"Exhibit {ex.number}" in render_cover(ex)


def test_page_ranges_contiguous_and_in_bounds_after_renumber():
    prop = proposals.propose(BRIEF, _simple_items())
    prop.set.add(source=Path("photo.pdf"), title="Wedding Photos",
                 proves="Evidences the wedding ceremony.",
                 content="\n".join(f"photo {i}" for i in range(60)), after=2)
    packet = paginate_set(prop.set)

    for ex in prop.set:
        assert ex.page_start is not None and ex.page_end is not None
        assert ex.page_start >= 1 and ex.page_end <= packet.total_pages
        assert ex.page_range.startswith("p")
    for a, b in zip(prop.set, prop.set[1:]):
        assert b.page_start == a.page_end + 1, "renumbered pages must stay contiguous"
    assert packet.total_pages == 1 + 1 + sum(
        1 + max(1, -(-len(ex.content.splitlines()) // 40)) for ex in prop.set
    )
