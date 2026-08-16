"""Facts, gaps, and the rule that no number is ever written by a model."""

from __future__ import annotations

import pytest

from afteraction.corpus import CorpusError, load_corpus
from afteraction.facts import (
    COMMUNICATIONS,
    MOBILISATION,
    OVERVIEW,
    TIMELINE,
    build_facts,
    declared_count_gaps,
)
from afteraction.models import Claim, Kind


@pytest.fixture(scope="module")
def storm_a():
    return build_facts(load_corpus("storm-a"))


@pytest.fixture(scope="module")
def storm_b():
    return build_facts(load_corpus("storm-b"))


def test_every_observed_claim_cites_a_real_log_entry(storm_a):
    known = storm_a.corpus.entry_ids
    observed = [c for c in storm_a.claims if c.kind is Kind.OBSERVED]
    assert observed
    for claim in observed:
        assert claim.sources
        assert set(claim.sources) <= known, f"{claim.claim_id} cites something outside the log"


def test_assessed_claims_never_borrow_evidence(storm_a):
    for claim in storm_a.claims:
        if claim.kind is Kind.ASSESSED:
            assert claim.sources == []


def test_a_claim_cannot_be_observed_without_a_source():
    with pytest.raises(ValueError, match="needs at least one log entry"):
        Claim(claim_id="x", kind=Kind.OBSERVED, section=TIMELINE, text="something", sources=[])


def test_judgement_cannot_dress_itself_as_evidence():
    with pytest.raises(ValueError, match="must not cite log entries"):
        Claim(claim_id="x", kind=Kind.ASSESSED, section=TIMELINE, text="a view", sources=["EL-0001"])


def test_peak_is_read_from_the_records_not_invented(storm_a):
    """74,600 appears in the report only because EL-0008 says so."""
    peak_claim = next(c for c in storm_a.for_section(OVERVIEW) if "peaked" in c.text)
    assert "74,600" in peak_claim.text
    assert "EL-0008" in peak_claim.sources
    entry = storm_a.corpus.entry("EL-0008")
    assert entry.consumers_out == 74600


def test_declared_gap_is_found_and_routine_cadence_is_not(storm_a):
    """The one real interruption is reported; the ordinary overnight spacing between
    counts is not, because a quiet stretch is a reporting cadence, not missing data."""
    gaps = declared_count_gaps(storm_a.corpus)
    assert len(gaps) == 1
    start, end = gaps[0]
    assert (start.entry_id, end.entry_id) == ("EL-0013", "EL-0015")

    timeline_gaps = storm_a.gaps_for(TIMELINE)
    assert len(timeline_gaps) == 1
    assert "3 hours 30 minutes" in timeline_gaps[0].detail


def test_an_event_with_no_declared_interruption_reports_no_count_gap(storm_b):
    assert declared_count_gaps(storm_b.corpus) == []
    assert storm_b.gaps_for(TIMELINE) == []


def test_crew_hours_exclude_crews_whose_records_cannot_support_them(storm_a):
    """Two crews have no mobilisation time. The total says so rather than guessing."""
    incomplete = [c for c in storm_a.corpus.crews if c.hours_worked is None]
    assert len(incomplete) == 2

    claim = next(c for c in storm_a.for_section(MOBILISATION) if "personnel-hours" in c.text)
    assert "9 of 11 crews" in claim.text
    assert "the remaining 2 have" in claim.text
    assert {g.subject for g in storm_a.gaps_for(MOBILISATION)} == {"CR-A10", "CR-A11"}


def test_an_unlogged_communication_is_reported_not_swallowed(storm_a):
    gaps = storm_a.gaps_for(COMMUNICATIONS)
    assert [g.subject for g in gaps] == ["CC-A06"]
    assert "no corresponding event-log entry" in gaps[0].detail


def test_notification_lag_is_computed_from_both_records(storm_a):
    """2 hours 41 minutes is arithmetic over EL-0004 and the comms record, not prose."""
    claim = next(c for c in storm_a.for_section(COMMUNICATIONS) if "first consumer notification" in c.text)
    assert "2 hours 41 minutes" in claim.text
    assert "EL-0004" in claim.sources


def test_storm_b_closed_the_gap_storm_a_opened(storm_b):
    claim = next(c for c in storm_b.for_section(COMMUNICATIONS) if "first consumer notification" in c.text)
    assert "38 minutes" in claim.text
    assert "0 hours" not in claim.text


def test_a_section_only_ever_offers_its_own_log_lines(storm_a):
    timeline = set(storm_a.sources_for(TIMELINE))
    comms = set(storm_a.sources_for(COMMUNICATIONS))
    assert timeline and comms
    assert "EL-0019" in timeline  # the safety entry belongs to the timeline
    assert "EL-0019" not in comms


def test_records_citing_a_nonexistent_entry_are_refused(tmp_path):
    """A gap is legitimate; a reference to something that was never logged is not."""
    import shutil

    from afteraction.corpus import DATA_ROOT

    root = tmp_path / "data"
    shutil.copytree(DATA_ROOT, root)
    crews = root / "storm-a" / "crew_records.csv"
    crews.write_text(crews.read_text(encoding="utf-8").replace("EL-0005", "EL-0999"), encoding="utf-8")

    with pytest.raises(CorpusError, match="not in the event log"):
        load_corpus("storm-a", root)
