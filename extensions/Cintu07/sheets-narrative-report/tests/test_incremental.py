"""Re-running after a data change must update only what moved.

The card's second criterion, tested the only way that means anything: render,
change a cell, re-render, and assert the untouched sections are byte-identical.
"""

import copy
from decimal import Decimal

import pytest

from narrative_report.facts import derive_facts, read_table
from narrative_report.incremental import (
    UntouchedSectionChanged,
    apply_plan,
    diff_facts,
    plan_update,
    verify_untouched,
)
from narrative_report.models import ReportManifest, Section
from narrative_report.numbers import referenced_keys, substitute

BASE = [
    ["Line item", "Q1", "Q2", "Q3", "Q4"],
    ["Revenue", "$1,200,000", "$1,320,000", "$1,180,000", "$1,455,000"],
    ["COGS", "(480,000)", "(528,000)", "(472,000)", "(560,000)"],
    ["Headcount", "42", "44", "44", "51"],
]

SUMMARY = (
    "<p>Across {{fact:period.count}} periods ending {{fact:period.last}}, revenue "
    "{{fact:series.revenue.direction}} to {{fact:series.revenue.latest}} "
    "({{fact:series.revenue.delta_pct}}).</p>"
)
COGS = (
    "<p>Cost of goods sold {{fact:series.cogs.direction}} "
    "{{fact:series.cogs.magnitude}} to {{fact:series.cogs.latest}} "
    "against the prior period.</p>"
)
PEOPLE = "<p>Headcount closed at {{fact:series.headcount.latest}}.</p>"


def build_manifest(rows):
    facts = derive_facts(read_table(rows, sheet="P&L", a1="B2:F6"))
    sections = []
    for sid, heading, template in [
        ("summary", "Summary", SUMMARY),
        ("cogs", "Cost of goods sold", COGS),
        ("people", "People", PEOPLE),
    ]:
        s = Section(id=sid, heading=heading, template=template, fact_keys=referenced_keys(template))
        s.rendered = substitute(template, facts).text
        sections.append(s)
    manifest = ReportManifest(
        report_id="r1",
        session_id="s1",
        source_range="P&L!B2:F6",
        sections=sections,
        fact_digests=facts.digests(),
        revision=1,
    )
    return manifest, facts


def edited(*cells):
    """Copy of BASE with individual cells replaced, each as (row_label, col, value)."""
    rows = copy.deepcopy(BASE)
    for label, col, value in cells:
        r = next(i for i, row in enumerate(rows) if row[0] == label)
        rows[r][col] = value
    return rows


class TestFactDiff:
    def test_detects_added_removed_and_changed(self):
        manifest, _ = build_manifest(BASE)
        new_facts = derive_facts(read_table(edited(("Revenue", 4, "$1,500,000")), "P&L", "B2:F6"))
        added, removed, changed = diff_facts(manifest.fact_digests, new_facts)
        assert not added and not removed
        assert "series.revenue.latest" in changed
        assert "series.headcount.latest" not in changed


class TestValueOnlyChange:
    """A figure moved but the sentence still reads correctly."""

    @pytest.fixture
    def scenario(self):
        manifest, _ = build_manifest(BASE)
        # 1,455,000 -> 1,500,000: still an increase, still "moved materially".
        facts = derive_facts(read_table(edited(("Revenue", 4, "$1,500,000")), "P&L", "B2:F6"))
        return manifest, facts, plan_update(manifest, facts)

    def test_only_the_affected_section_is_touched(self, scenario):
        _, _, plan = scenario
        actions = {p.section.id: p.action for p in plan.sections}
        assert actions == {"summary": "resubstitute", "cogs": "keep", "people": "keep"}

    def test_costs_no_operations(self, scenario):
        _, _, plan = scenario
        # The whole point: an update should cost like an update.
        assert plan.billable_operations == 0

    def test_untouched_sections_are_byte_identical(self, scenario):
        manifest, facts, plan = scenario
        rendered = apply_plan(plan, facts)
        verify_untouched(plan, rendered)  # raises if anything drifted
        for entry in plan.kept:
            assert rendered[entry.section.id] == entry.section.rendered

    def test_the_touched_section_actually_updated(self, scenario):
        _, facts, plan = scenario
        rendered = apply_plan(plan, facts)
        assert "$1,500,000" in rendered["summary"]
        assert "$1,455,000" not in rendered["summary"]


class TestWordingChange:
    """A figure moved far enough that the words around it are now wrong."""

    def test_direction_flip_forces_a_rewrite(self):
        manifest, _ = build_manifest(BASE)
        # Revenue falls below the prior period: "increased" becomes "decreased".
        facts = derive_facts(read_table(edited(("Revenue", 4, "$900,000")), "P&L", "B2:F6"))
        plan = plan_update(manifest, facts)
        actions = {p.section.id: p.action for p in plan.sections}
        assert actions["summary"] == "regenerate"
        assert actions["cogs"] == "keep"
        assert plan.billable_operations == 1

    def test_crossing_a_magnitude_band_forces_a_rewrite(self):
        manifest, _ = build_manifest(BASE)
        # COGS -560,000 -> -472,001: the move collapses from "moved modestly"
        # into "held broadly flat", so "having moved modestly" is now a lie.
        facts = derive_facts(read_table(edited(("COGS", 4, "(472,100)")), "P&L", "B2:F6"))
        plan = plan_update(manifest, facts)
        actions = {p.section.id: p.action for p in plan.sections}
        assert actions["cogs"] == "regenerate"
        assert actions["people"] == "keep"

    def test_regeneration_only_replaces_the_supplied_section(self):
        manifest, _ = build_manifest(BASE)
        facts = derive_facts(read_table(edited(("Revenue", 4, "$900,000")), "P&L", "B2:F6"))
        plan = plan_update(manifest, facts)
        rewritten = {"summary": "<p>Revenue fell to {{fact:series.revenue.latest}}.</p>"}
        rendered = apply_plan(plan, facts, regenerated=rewritten)
        assert rendered["summary"] == "<p>Revenue fell to $900,000.</p>"
        verify_untouched(plan, rendered)


class TestNoChange:
    def test_identical_data_is_a_noop(self):
        manifest, facts = build_manifest(BASE)
        plan = plan_update(manifest, facts)
        assert plan.is_noop
        assert plan.billable_operations == 0
        rendered = apply_plan(plan, facts)
        verify_untouched(plan, rendered)
        assert rendered == {s.id: s.rendered for s in manifest.sections}


class TestStructuralChange:
    def test_removing_a_line_item_forces_a_rewrite_of_dependants(self):
        manifest, _ = build_manifest(BASE)
        without_cogs = [r for r in BASE if r[0] != "COGS"]
        facts = derive_facts(read_table(without_cogs, "P&L", "B2:F5"))
        plan = plan_update(manifest, facts)
        actions = {p.section.id: p.action for p in plan.sections}
        assert actions["cogs"] == "regenerate"
        assert actions["people"] == "keep"
        assert "cogs" in plan.series_removed

    def test_adding_a_line_item_is_reported(self):
        manifest, _ = build_manifest(BASE)
        rows = copy.deepcopy(BASE) + [["Marketing", "90,000", "95,000", "88,000", "120,000"]]
        facts = derive_facts(read_table(rows, "P&L", "B2:F7"))
        plan = plan_update(manifest, facts)
        assert "marketing" in plan.series_added
        # Existing sections do not reference the new series, so they stand.
        assert {p.action for p in plan.sections} == {"keep"}


class TestGuardrail:
    def test_verify_untouched_catches_drift(self):
        manifest, facts = build_manifest(BASE)
        plan = plan_update(manifest, facts)
        rendered = apply_plan(plan, facts)
        rendered["people"] = "<p>Headcount closed at 999.</p>"
        with pytest.raises(UntouchedSectionChanged, match="people"):
            verify_untouched(plan, rendered)


class TestManifestRoundTrip:
    def test_survives_serialisation(self):
        manifest, _ = build_manifest(BASE)
        restored = ReportManifest.from_json(manifest.to_json())
        assert restored.fact_digests == manifest.fact_digests
        assert [s.id for s in restored.sections] == [s.id for s in manifest.sections]
        assert restored.sections[0].rendered == manifest.sections[0].rendered
        assert restored.sections[0].fact_keys == manifest.sections[0].fact_keys

    def test_digest_ignores_provenance_but_not_value(self):
        manifest, facts = build_manifest(BASE)
        moved = derive_facts(read_table(edited(("Revenue", 4, "$1,455,001")), "P&L", "B2:F6"))
        assert moved["series.revenue.latest"].digest() != facts["series.revenue.latest"].digest()
        assert moved["series.headcount.latest"].digest() == facts["series.headcount.latest"].digest()

    def test_decimal_values_survive_the_round_trip_exactly(self):
        _, facts = build_manifest(BASE)
        assert facts["series.revenue.total"].value == Decimal("5155000")
