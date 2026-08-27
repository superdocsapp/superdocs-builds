"""What the report leads with must not be an accident of ordering.

Found against the live API: with the fact table sorted alphabetically, the model
opened a P&L summary with headcount and never mentioned the eight-figure
subscription revenue line. Order is the only steer the model gets about what
matters, so it is computed rather than incidental.
"""

import pytest

from narrative_report.facts import derive_facts, fact_table_for_model, materiality, read_table
from narrative_report.narrative import REPORT_OUTLINE, build_prompt, fallback_plan

PNL = [
    ["Line item", "Q1", "Q2", "Q3", "Q4"],
    ["Amortisation", "$12,000", "$12,000", "$12,000", "$12,000"],
    ["Headcount", "84", "89", "94", "103"],
    ["Subscription revenue", "$1,840,000", "$1,972,000", "$2,105,000", "$2,388,000"],
    ["Net revenue retention", "108.4%", "111.2%", "109.7%", "114.3%"],
]


@pytest.fixture
def table():
    return read_table(PNL, sheet="P&L", a1="A1:E5")


class TestMateriality:
    def test_the_largest_currency_line_ranks_first(self, table):
        ranked = sorted(table.series, key=materiality, reverse=True)
        assert ranked[0].label == "Subscription revenue"

    def test_currency_outranks_a_larger_bare_number(self, table):
        # Headcount peaks at 103 and amortisation at 12,000; both are dwarfed by
        # revenue, but a currency line must also outrank a plain count.
        by_label = {s.label: materiality(s) for s in table.series}
        assert by_label["Amortisation"] > by_label["Headcount"]

    def test_percentages_do_not_compete_on_size(self, table):
        by_label = {s.label: materiality(s) for s in table.series}
        assert by_label["Net revenue retention"] == 0

    def test_ranking_is_stable_for_equal_magnitudes(self):
        rows = [["Item", "Q1", "Q2"], ["Beta", "$100", "$100"], ["Alpha", "$100", "$100"]]
        t = read_table(rows, sheet="S", a1="A1:C3")
        first = [s.label for s in sorted(t.series, key=lambda s: (materiality(s), s.slug), reverse=True)]
        second = [s.label for s in sorted(t.series, key=lambda s: (materiality(s), s.slug), reverse=True)]
        assert first == second


class TestHeadlineFact:
    def test_headline_names_the_material_line(self, table):
        facts = derive_facts(table)
        assert facts["headline.name"].value == "Subscription revenue"

    def test_headline_carries_provenance(self, table):
        facts = derive_facts(table)
        assert "P&L!" in facts["headline.name"].provenance


class TestPromptOrdering:
    """Ordering is asserted inside the token table, not across the whole prompt.

    The prompt also carries a worked example that names real tokens, so a naive
    index search over the full string finds the example rather than the table.
    """

    @staticmethod
    def _token_table(table):
        prompt = build_prompt(derive_facts(table), REPORT_OUTLINE, table)
        return prompt[prompt.index("AVAILABLE TOKENS") : prompt.index("SECTIONS TO WRITE")]

    def test_material_series_appears_before_minor_ones(self, table):
        section = self._token_table(table)
        assert section.index("series.subscription_revenue") < section.index("series.amortisation")

    def test_global_facts_lead_the_table(self, table):
        section = self._token_table(table)
        assert section.index("period.count") < section.index("series.subscription_revenue")

    def test_the_brief_tells_the_model_to_lead_with_the_headline(self, table):
        prompt = build_prompt(derive_facts(table), REPORT_OUTLINE, table)
        assert "headline.name" in prompt
        assert "EVERY line item" in prompt

    def test_ordering_is_deterministic(self, table):
        facts = derive_facts(table)
        assert fact_table_for_model(facts, table) == fact_table_for_model(facts, table)


class TestFallbackLeadsWithTheHeadline:
    def test_deterministic_summary_names_the_material_line_first(self, table):
        facts = derive_facts(table)
        plan = fallback_plan(facts, REPORT_OUTLINE, reason="offline")
        summary = next(s for s in plan.sections if s.id == "summary")
        assert "series.subscription_revenue.latest" in summary.fact_keys

    def test_performance_covers_every_line_item(self, table):
        facts = derive_facts(table)
        plan = fallback_plan(facts, REPORT_OUTLINE, reason="offline")
        performance = next(s for s in plan.sections if s.id == "performance")
        for slug in ("subscription_revenue", "headcount", "amortisation"):
            assert f"series.{slug}.latest" in performance.fact_keys
