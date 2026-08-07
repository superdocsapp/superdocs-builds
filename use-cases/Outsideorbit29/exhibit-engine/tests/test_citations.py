"""In-brief citations: proposed at the sentences the brief relies on, spliced
back in on approval, and renumbered together when the set changes."""

from __future__ import annotations

from pathlib import Path

from exhibit import proposals
from exhibit.citations import apply_citations, plan_citations
from exhibit.model import ExhibitSet


BRIEF = (
    "The applicant's identity is established by his passport. The marriage is "
    "shown by the marriage certificate. The couple lives together under a joint "
    "lease. Their finances are intermingled through joint bank accounts. For "
    "these reasons the petition should be granted."
)


def _two_exhibit_set() -> ExhibitSet:
    set_ = ExhibitSet()
    set_.add(source=Path("passport.pdf"), title="Passport",
             proves="Evidences identity, nationality and birth.",
             content="passport identity nationality birth visa")
    set_.add(source=Path("lease.pdf"), title="Joint Lease",
             proves="Evidences the joint lease on the residence.",
             content="lease residence joint home together")
    return set_


def test_plan_citations_proposes_one_per_exhibit():
    set_ = _two_exhibit_set()
    citations = plan_citations(set_, BRIEF)
    assert len(citations) == 2
    # each citation points at an exhibit that exists
    for c in citations:
        set_.by_number(c.exhibit_number)


def test_citation_anchors_at_the_relying_sentence():
    set_ = _two_exhibit_set()
    citations = {c.exhibit_number: c for c in plan_citations(set_, BRIEF)}
    lease = citations[set_.by_number(2).number if len(set_) >= 2 else 1]
    # the lease exhibit should be anchored at the joint-lease sentence
    assert "joint lease" in lease.anchor


def test_apply_citations_inserts_markers_at_anchors():
    set_ = _two_exhibit_set()
    citations = plan_citations(set_, BRIEF)
    edited = apply_citations(BRIEF, citations)
    for c in citations:
        assert f"[See Exhibit {c.exhibit_number}]" in edited
    assert len(edited) > len(BRIEF)


def test_apply_citations_is_idempotent():
    set_ = _two_exhibit_set()
    edited_once = apply_citations(BRIEF, plan_citations(set_, BRIEF))
    edited_twice = apply_citations(edited_once, plan_citations(set_, BRIEF))
    assert edited_once.count("[See Exhibit") == edited_twice.count("[See Exhibit")


def test_unrelated_exhibit_gets_uncited_sentence():
    set_ = ExhibitSet()
    set_.add(source=Path("blueprint.pdf"), title="Blueprint",
             proves="Evidences engineering drawings.",
             content="cad drawings engineering schematic dimensions")
    citations = plan_citations(set_, BRIEF)
    # no sentence in the brief is about blueprints, so it takes the earliest
    # uncited sentence and says so in its rationale
    assert citations[0].anchor
    assert "No direct topical match" in citations[0].rationale


def test_late_insert_changes_citation_numbers_together():
    set_ = _two_exhibit_set()
    before = {c.anchor: c.exhibit_number for c in plan_citations(set_, BRIEF)}
    # Insert a new exhibit before the lease; the lease (and its citation) shifts.
    set_.add(source=Path("photo.pdf"), title="Photos",
             proves="Evidences the wedding.",
             content="wedding photographs ceremony", after=0)
    after = {c.anchor: c.exhibit_number for c in plan_citations(set_, BRIEF)}
    lease_anchor = next(a for a in before if "joint lease" in a)
    assert after[lease_anchor] == before[lease_anchor] + 1
