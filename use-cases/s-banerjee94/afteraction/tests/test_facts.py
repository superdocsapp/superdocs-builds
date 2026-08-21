"""Facts, gaps, and the rule that no number is ever written by a model."""

from __future__ import annotations

import pytest

from afteraction.corpus import CorpusError, load_corpus
from afteraction.facts import (
    COMMUNICATIONS,
    DAMAGE,
    MOBILISATION,
    OVERVIEW,
    TIMELINE,
    build_facts,
    declared_count_gaps,
)
from afteraction.models import Claim, DamageStatus, Kind


@pytest.fixture(scope="module")
def storm_a():
    return build_facts(load_corpus("storm-a"))


@pytest.fixture(scope="module")
def storm_b():
    return build_facts(load_corpus("storm-b"))


def test_every_observed_claim_cites_a_real_record(storm_a):
    known = storm_a.corpus.entry_ids
    observed = [c for c in storm_a.claims if c.kind is Kind.OBSERVED]
    assert observed
    for claim in observed:
        assert claim.sources
        assert set(claim.sources) <= known, f"{claim.claim_id} cites something outside the records"


def test_assessed_claims_never_borrow_evidence(storm_a):
    for claim in storm_a.claims:
        if claim.kind is Kind.ASSESSED:
            assert claim.sources == []


def test_a_claim_cannot_be_observed_without_a_source():
    with pytest.raises(ValueError, match="needs at least one record"):
        Claim(claim_id="x", kind=Kind.OBSERVED, section=TIMELINE, text="something", sources=[])


def test_judgement_cannot_dress_itself_as_evidence():
    with pytest.raises(ValueError, match="must not cite records"):
        Claim(claim_id="x", kind=Kind.ASSESSED, section=TIMELINE, text="a view", sources=["TEL-0001"])


def test_peak_is_read_from_the_records_not_invented(storm_a):
    """17,790 appears in the report only because TEL-0005 says so."""
    peak_claim = next(c for c in storm_a.for_section(OVERVIEW) if "peaked" in c.text)
    assert "17,790" in peak_claim.text
    assert "TEL-0005" in peak_claim.sources
    entry = storm_a.corpus.entry("TEL-0005")
    assert entry.consumers_out == 17790


def test_declared_gap_is_found_and_routine_cadence_is_not(storm_a):
    """The one real interruption is reported; the ordinary overnight spacing between
    counts is not, because a quiet stretch is a reporting cadence, not missing data."""
    gaps = declared_count_gaps(storm_a.corpus)
    assert len(gaps) == 1
    start, end = gaps[0]
    assert (start.entry_id, end.entry_id) == ("TEL-0008", "TEL-0009")

    timeline_gaps = storm_a.gaps_for(TIMELINE)
    assert len(timeline_gaps) == 1
    assert "3 hours 45 minutes" in timeline_gaps[0].detail
    # A gap names the record it is about, and that name is a citation like any other.
    assert set(timeline_gaps[0].sources) == {"TEL-0008", "TEL-0009"}


def test_an_event_with_no_declared_interruption_reports_no_count_gap(storm_b):
    assert declared_count_gaps(storm_b.corpus) == []
    assert storm_b.gaps_for(TIMELINE) == []


def test_crew_hours_exclude_crews_whose_records_cannot_support_them(storm_a):
    """Three crews have incomplete records. The total says so rather than guessing."""
    incomplete = [c for c in storm_a.corpus.crews if c.hours_worked is None]
    assert len(incomplete) == 3

    claim = next(c for c in storm_a.for_section(MOBILISATION) if "personnel-hours" in c.text)
    assert "5 of 8 crews" in claim.text
    assert "the remaining 3 have" in claim.text
    assert {g.subject for g in storm_a.gaps_for(MOBILISATION)} == {"CRW-0005", "CRW-0006", "CRW-0008"}


def test_a_contact_that_was_never_answered_is_reported_not_swallowed(storm_a):
    """Two consumer contacts carried no resolution time when the event closed.

    Inbound contacts are the stream a single event log loses entirely, and an
    unanswered one is a fact about the response rather than a rounding error.
    """
    gaps = storm_a.gaps_for(COMMUNICATIONS)
    unanswered = [g for g in gaps if g.subject.startswith("COM-")]
    assert {g.subject for g in unanswered} == {"COM-0005", "COM-0014"}
    assert "carried no resolution time when the event closed" in unanswered[0].detail


def test_notification_lag_is_computed_from_both_records(storm_a):
    """2 hours 13 minutes is arithmetic over TEL-0001 and COM-0003, not prose."""
    claim = next(
        c for c in storm_a.for_section(COMMUNICATIONS) if "first consumer notification" in c.text
    )
    assert "2 hours 13 minutes" in claim.text
    assert "TEL-0001" in claim.sources


def test_storm_b_closed_the_gap_storm_a_opened(storm_b):
    claim = next(
        c for c in storm_b.for_section(COMMUNICATIONS) if "first consumer notification" in c.text
    )
    assert "38 minutes" in claim.text
    assert "0 hours" not in claim.text


def test_inbound_and_outbound_are_counted_separately(storm_a):
    """A single event log records only what the utility said. Both directions are
    reported, because a commission asks how many consumers called."""
    texts = [c.text for c in storm_a.for_section(COMMUNICATIONS)]
    assert any("notifications were issued to consumers" in t for t in texts)
    assert any("consumer contacts were received" in t for t in texts)


def test_reported_damage_is_never_added_to_confirmed_damage(storm_a):
    """DMG-0006 is one consumer's word about a pole nobody inspected.

    Counting it alongside confirmed damage would assert more broken poles than were
    ever broken, which is the exact failure the six-file split exists to prevent.
    """
    confirmed = storm_a.corpus.damage_totals(DamageStatus.CONFIRMED, DamageStatus.REPAIRED)
    everything = storm_a.corpus.damage_totals()
    assert confirmed[next(iter(confirmed))] >= 1
    # the unverified pole is in the unfiltered total and in no claim
    assert everything["pole"] == confirmed["pole"] + 1

    claim = next(c for c in storm_a.for_section(DAMAGE) if "Confirmed damage" in c.text)
    assert "DMG-0006" not in claim.sources

    gap = next(g for g in storm_a.gaps_for(DAMAGE) if g.subject == "DMG-0006")
    assert "never inspected" in gap.detail
    assert "excluded from the confirmed totals" in gap.detail


def test_damage_records_report_where_they_came_from(storm_a):
    """Three grades of evidence for one kind of fact, kept apart and stated."""
    claim = next(c for c in storm_a.for_section(DAMAGE) if "damage records were raised" in c.text)
    assert "a consumer contact" in claim.text
    assert "network telemetry" in claim.text
    assert "a crew on site" in claim.text


def test_a_section_only_ever_offers_its_own_records(storm_a):
    timeline = set(storm_a.sources_for(TIMELINE))
    comms = set(storm_a.sources_for(COMMUNICATIONS))
    assert timeline and comms
    assert "FLD-0007" in timeline  # the safety report belongs to the timeline
    assert "FLD-0007" not in comms


def test_records_citing_a_nonexistent_entry_are_refused(tmp_path):
    """A gap is legitimate; a reference to something that was never recorded is not."""
    import shutil

    from afteraction.corpus import DATA_ROOT

    root = tmp_path / "data"
    shutil.copytree(DATA_ROOT, root)
    crews = root / "storm-a" / "crew.csv"
    crews.write_text(
        crews.read_text(encoding="utf-8").replace("TEL-0001", "TEL-0999"), encoding="utf-8"
    )

    with pytest.raises(CorpusError, match="not in any record set"):
        load_corpus("storm-a", root)


def test_a_damage_record_cannot_cite_a_contact_that_never_happened(tmp_path):
    """The chain from a consumer's call to a repair only means something if the call
    is real. A damage record pointing at a contact id nobody logged is a data error."""
    import shutil

    from afteraction.corpus import DATA_ROOT

    root = tmp_path / "data"
    shutil.copytree(DATA_ROOT, root)
    damage = root / "storm-a" / "damage.csv"
    damage.write_text(
        damage.read_text(encoding="utf-8").replace(",COM-0002,", ",COM-0999,"), encoding="utf-8"
    )

    with pytest.raises(CorpusError, match="not in any record set"):
        load_corpus("storm-a", root)
