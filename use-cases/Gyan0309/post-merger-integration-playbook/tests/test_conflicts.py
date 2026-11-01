"""Conflict detection, tested exhaustively with no API key.

Detection is pure arithmetic over the deal spec, so it earns thorough testing and gets
it in milliseconds. The valuable tests here are the ones asserting a comparator stays
**silent** — a detector that fires on everything is worthless in a way that is easy to
miss, because every "it found the thing" test still passes.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from imo.conflicts import (  # noqa: E402
    conflicts_for,
    detect,
    find_contested_dependencies,
    find_duplicate_synergies,
    find_synergy_over_commitment,
    find_unmet_day_one,
)
from imo.deal import (  # noqa: E402
    DayOneItem,
    Deal,
    Dependency,
    Synergy,
    TargetProfile,
    Workstream,
)


def _deal(workstreams, *, target=Decimal(10_000_000)) -> Deal:
    return Deal(
        code_name="Test",
        acquirer="Acquirer Ltd",
        target="Target Ltd",
        announced=date(2026, 1, 1),
        expected_close=date(2026, 3, 1),
        integration_horizon_months=12,
        deal_value_usd=Decimal(50_000_000),
        synergy_target_usd=target,
        rationale="",
        profile=TargetProfile(headcount=100, locations=["X"], systems=[]),
        workstreams=workstreams,
    )


def _ws(key, *, synergies=(), dependencies=(), day_one=()) -> Workstream:
    return Workstream(
        key=key,
        name=key.title(),
        lead="Lead",
        scope="",
        synergies=list(synergies),
        dependencies=list(dependencies),
        day_one=list(day_one),
    )


def _syn(id_, description, value, owner, month=6) -> Synergy:
    return Synergy(
        id=id_,
        description=description,
        annual_value_usd=Decimal(value),
        realisation_month=month,
        owner=owner,
    )


def _dep(id_, description, owner, month=3) -> Dependency:
    return Dependency(id=id_, description=description, owner=owner, needed_by_month=month)


class TestDuplicateSynergy:
    def test_identical_ids_across_workstreams_are_caught(self) -> None:
        deal = _deal(
            [
                _ws("finance", synergies=[_syn("SYN-1", "Retire ERP licences", 500_000, "finance")]),
                _ws("tech", synergies=[_syn("SYN-1", "Retire ERP licences", 400_000, "tech")]),
            ]
        )
        found = find_duplicate_synergies(deal)
        assert len(found) == 1
        assert set(found[0].affects) == {"finance", "tech"}

    def test_near_identical_descriptions_are_caught(self) -> None:
        """The realistic failure: the same saving under two different ids."""
        deal = _deal(
            [
                _ws("finance", synergies=[
                    _syn("SYN-F2", "Terminate external analytics vendor contracts", 1_800_000, "finance")
                ]),
                _ws("tech", synergies=[
                    _syn("SYN-T1", "Terminate the external analytics vendor contracts and platforms", 1_520_000, "tech")
                ]),
            ]
        )
        assert len(find_duplicate_synergies(deal)) == 1

    def test_genuinely_different_savings_are_not_flagged(self) -> None:
        """The most important silence. Integration language is repetitive — 'consolidate
        X systems' appears in every workstream — and a detector that flags all of them
        trains people to ignore the report."""
        deal = _deal(
            [
                _ws("finance", synergies=[_syn("SYN-1", "Consolidate finance systems", 500_000, "finance")]),
                _ws("people", synergies=[_syn("SYN-2", "Consolidate HR tooling", 300_000, "people")]),
            ]
        )
        assert find_duplicate_synergies(deal) == []

    def test_one_workstream_with_two_similar_claims_is_its_own_business(self) -> None:
        """Not a cross-workstream conflict. One owner can split a saving how they like."""
        deal = _deal(
            [
                _ws("finance", synergies=[
                    _syn("SYN-1", "Terminate vendor contracts phase one", 500_000, "finance"),
                    _syn("SYN-2", "Terminate vendor contracts phase two", 400_000, "finance"),
                ])
            ]
        )
        assert find_duplicate_synergies(deal) == []

    def test_the_finding_quantifies_the_overstatement(self) -> None:
        """A conflict a reader cannot act on is noise. The smaller claim is the amount
        the total is inflated by."""
        deal = _deal(
            [
                _ws("finance", synergies=[_syn("SYN-1", "Retire ERP licences", 500_000, "finance")]),
                _ws("tech", synergies=[_syn("SYN-1", "Retire ERP licences", 400_000, "tech")]),
            ]
        )
        assert "$400,000" in find_duplicate_synergies(deal)[0].detail


class TestContestedDependency:
    def test_two_owners_of_the_same_deliverable_are_caught(self) -> None:
        deal = _deal(
            [
                _ws("commercial", dependencies=[_dep("DEP-CRM", "Migrate CRM records to Salesforce", "commercial")]),
                _ws("tech", dependencies=[_dep("DEP-CRM-2", "Migrate CRM records into Salesforce", "tech")]),
            ]
        )
        found = find_contested_dependencies(deal)
        assert len(found) == 1
        assert set(found[0].affects) == {"commercial", "tech"}

    def test_unrelated_dependencies_are_not_flagged(self) -> None:
        deal = _deal(
            [
                _ws("commercial", dependencies=[_dep("DEP-1", "Novate customer contracts", "commercial")]),
                _ws("tech", dependencies=[_dep("DEP-2", "Extend single sign-on to staff", "tech")]),
            ]
        )
        assert find_contested_dependencies(deal) == []


class TestSynergyOverCommitment:
    def test_claims_above_target_are_flagged(self) -> None:
        deal = _deal(
            [_ws("finance", synergies=[_syn("SYN-1", "Saving", 6_000_000, "finance")])],
            target=Decimal(4_000_000),
        )
        found = find_synergy_over_commitment(deal)
        assert len(found) == 1
        assert "$2,000,000" in found[0].detail

    def test_claims_at_target_are_not_flagged(self) -> None:
        """Boundary. Exactly on target is on target, not over it."""
        deal = _deal(
            [_ws("finance", synergies=[_syn("SYN-1", "Saving", 4_000_000, "finance")])],
            target=Decimal(4_000_000),
        )
        assert find_synergy_over_commitment(deal) == []

    def test_under_commitment_is_not_reported_here(self) -> None:
        deal = _deal(
            [_ws("finance", synergies=[_syn("SYN-1", "Saving", 1_000_000, "finance")])],
            target=Decimal(4_000_000),
        )
        assert find_synergy_over_commitment(deal) == []

    def test_every_claiming_workstream_shares_the_finding(self) -> None:
        """No single lead can resolve it, and showing it only centrally lets all of
        them assume it is someone else's number that is wrong."""
        deal = _deal(
            [
                _ws("finance", synergies=[_syn("SYN-1", "A", 3_000_000, "finance")]),
                _ws("tech", synergies=[_syn("SYN-2", "B", 3_000_000, "tech")]),
                _ws("people"),  # claims nothing
            ],
            target=Decimal(4_000_000),
        )
        found = find_synergy_over_commitment(deal)
        assert set(found[0].affects) == {"finance", "tech"}
        assert "people" not in found[0].affects


class TestUnmetDayOne:
    def test_an_item_depending_on_later_work_is_caught(self) -> None:
        deal = _deal(
            [
                _ws(
                    "people",
                    dependencies=[_dep("DEP-PAY", "Payroll cutover", "people", month=2)],
                    day_one=[DayOneItem(id="DAY-1", description="Staff paid", owner="people", depends_on=["DEP-PAY"])],
                )
            ]
        )
        found = find_unmet_day_one(deal)
        assert len(found) == 1
        assert "month 2" in found[0].summary

    def test_an_item_depending_on_day_zero_work_is_fine(self) -> None:
        """`needed_by_month: 0` means it is ready at close. That is not a conflict."""
        deal = _deal(
            [
                _ws(
                    "people",
                    dependencies=[_dep("DEP-PAY", "Payroll cutover", "people", month=0)],
                    day_one=[DayOneItem(id="DAY-1", description="Staff paid", owner="people", depends_on=["DEP-PAY"])],
                )
            ]
        )
        assert find_unmet_day_one(deal) == []

    def test_an_item_with_no_dependencies_is_fine(self) -> None:
        deal = _deal(
            [_ws("people", day_one=[DayOneItem(id="DAY-1", description="Letters sent", owner="people")])]
        )
        assert find_unmet_day_one(deal) == []

    def test_both_the_item_owner_and_the_dependency_owner_are_told(self) -> None:
        """Neither can fix it alone: one must move the item, the other must pull the
        dependency forward."""
        deal = _deal(
            [
                _ws("tech", dependencies=[_dep("DEP-SSO", "Single sign-on", "tech", month=1)]),
                _ws("people", day_one=[DayOneItem(id="DAY-1", description="Staff can log in", owner="people", depends_on=["DEP-SSO"])]),
            ]
        )
        found = find_unmet_day_one(deal)
        assert set(found[0].affects) == {"people", "tech"}


class TestFanOut:
    """The card's headline requirement, at the data level."""

    @pytest.fixture
    def deal(self) -> Deal:
        return _deal(
            [
                _ws("finance", synergies=[_syn("SYN-1", "Retire ERP licences", 500_000, "finance")]),
                _ws("tech", synergies=[_syn("SYN-1", "Retire ERP licences", 400_000, "tech")]),
                _ws("people"),
            ]
        )

    def test_a_conflict_reaches_both_parties(self, deal) -> None:
        conflicts = detect(deal)
        assert conflicts_for(conflicts, "finance"), "finance must see it"
        assert conflicts_for(conflicts, "tech"), "tech must see it"

    def test_an_uninvolved_workstream_is_not_told(self, deal) -> None:
        """Fanning out to everyone is the same as not fanning out at all: it teaches
        readers that most flags are not theirs."""
        assert conflicts_for(detect(deal), "people") == []


class TestCleanDeal:
    def test_a_consistent_deal_produces_no_conflicts(self) -> None:
        """A reassuring nothing is a real answer. Manufacturing a finding to justify
        the check having run is worse than finding none."""
        deal = _deal(
            [
                _ws(
                    "finance",
                    synergies=[_syn("SYN-1", "Retire ERP licences", 500_000, "finance")],
                    dependencies=[_dep("DEP-COA", "Single chart of accounts", "finance")],
                    day_one=[DayOneItem(id="DAY-1", description="Balance sheet signed", owner="finance")],
                ),
                _ws("people", synergies=[_syn("SYN-2", "Remove duplicate HR tooling", 300_000, "people")]),
            ],
            target=Decimal(4_000_000),
        )
        assert detect(deal) == []


class TestDeterminism:
    def test_detection_is_stable_across_runs(self) -> None:
        """Ordering must not wobble, or every regeneration produces a spurious diff."""
        deal = _deal(
            [
                _ws("finance", synergies=[_syn("SYN-1", "Retire ERP licences", 500_000, "finance")]),
                _ws("tech", synergies=[_syn("SYN-1", "Retire ERP licences", 400_000, "tech")]),
            ]
        )
        assert [c.id for c in detect(deal)] == [c.id for c in detect(deal)]

    def test_high_severity_sorts_first(self) -> None:
        deal = _deal(
            [
                _ws("finance", synergies=[_syn("SYN-1", "Retire ERP licences", 3_000_000, "finance")]),
                _ws("tech", synergies=[_syn("SYN-1", "Retire ERP licences", 3_000_000, "tech")]),
            ],
            target=Decimal(1_000_000),
        )
        severities = [c.severity for c in detect(deal)]
        assert severities == sorted(severities, key=lambda s: {"high": 0, "medium": 1}.get(s, 2))
