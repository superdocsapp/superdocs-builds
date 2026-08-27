"""A claim about a pattern is a claim, and has to be grounded like a number.

Found live. The model wrote "revenue closed Q4 at $2,388,000, marking the fourth
consecutive period of growth". The figure was grounded and correct. The claim
that the growth was *consecutive* was the model's own inference, and nothing
checked it, so grounding every number was not sufficient on its own.

Two halves to the fix, both tested here: the run is computed as a fact so the
model has a true way to say it, and pattern words it types itself are reported.
"""

from decimal import Decimal

import pytest

from narrative_report.facts import derive_facts, describe_streak, read_table
from narrative_report.models import FactSet
from narrative_report.numbers import find_ungrounded_quantity_words, substitute


def dec(*values):
    return [Decimal(str(v)) for v in values]


class TestTheRunIsComputed:
    @pytest.mark.parametrize(
        "values,expected",
        [
            (dec(10, 20, 30, 40), "the third consecutive period of growth"),
            (dec(40, 30, 20, 10), "the third consecutive period of decline"),
            (dec(10, 20, 30), "the second consecutive period of growth"),
            (dec(50, 10, 20, 30), "the second consecutive period of growth"),
        ],
    )
    def test_runs_are_counted_and_named(self, values, expected):
        assert describe_streak(values) == expected

    @pytest.mark.parametrize(
        "values",
        [
            dec(10, 20),           # two points is a change, not a trend
            dec(10, 20, 15),       # the run was broken by the latest move
            dec(30, 10, 20),       # only one move in the current direction
            dec(10, 20, 20),       # the latest period did not move at all
            dec(10),               # nothing to compare
        ],
    )
    def test_refuses_to_describe_a_run_that_is_not_there(self, values):
        # No token means the model has nothing to say, which is the point.
        assert describe_streak(values) is None

    def test_a_long_run_is_described_without_inventing_an_ordinal(self):
        assert describe_streak(dec(*range(1, 30))) == "part of a long unbroken run of growth"


class TestTheFactReachesTheReport:
    @pytest.fixture
    def rising(self):
        return read_table(
            [
                ["Line item", "Q1", "Q2", "Q3", "Q4"],
                ["Revenue", "$1,000", "$1,200", "$1,400", "$1,700"],
                ["Costs", "$500", "$400", "$600", "$450"],
            ],
            sheet="P&L",
            a1="A1:E3",
        )

    def test_a_real_run_gets_a_token(self, rising):
        facts = derive_facts(rising)
        assert facts["series.revenue.streak"].value == "the third consecutive period of growth"

    def test_a_line_with_no_run_gets_no_token(self, rising):
        # Costs went down, up, down. There is no run, so there is no token.
        facts = derive_facts(rising)
        assert "series.costs.streak" not in facts

    def test_the_fact_carries_provenance(self, rising):
        assert "P&L!" in derive_facts(rising)["series.revenue.streak"].provenance

    def test_the_streak_changes_when_the_run_breaks(self, rising):
        """A broken run must invalidate the sentence, not just the figure."""
        broken = read_table(
            [
                ["Line item", "Q1", "Q2", "Q3", "Q4"],
                ["Revenue", "$1,000", "$1,200", "$1,400", "$900"],
            ],
            sheet="P&L",
            a1="A1:E2",
        )
        before = derive_facts(rising)["series.revenue.streak"]
        assert "series.revenue.streak" not in derive_facts(broken)
        assert before.value  # it existed before the data moved


class TestPatternClaimsAreCaught:
    @pytest.mark.parametrize(
        "phrase",
        [
            "the fourth consecutive period of growth",
            "revenue grew consistently",
            "up every quarter",
            "a clear upward trend",
            "the momentum continues",
            "steadily climbing",
        ],
    )
    def test_a_pattern_claim_the_model_typed_is_reported(self, phrase):
        rendered = substitute(f"<p>Revenue rose. {phrase}.</p>", FactSet([]))
        assert find_ungrounded_quantity_words(rendered), phrase

    def test_the_same_claim_from_a_token_is_not_reported(self, rising_facts):
        # Identical words, but this time they came from the sheet.
        rendered = substitute(
            "<p>Revenue closed at {{fact:series.revenue.latest}}, "
            "{{fact:series.revenue.streak}}.</p>",
            rising_facts,
        )
        assert find_ungrounded_quantity_words(rendered) == []

    @pytest.fixture
    def rising_facts(self):
        return derive_facts(
            read_table(
                [
                    ["Line item", "Q1", "Q2", "Q3", "Q4"],
                    ["Revenue", "$1,000", "$1,200", "$1,400", "$1,700"],
                ],
                sheet="P&L",
                a1="A1:E2",
            )
        )

    def test_ordinary_prose_is_left_alone(self):
        rendered = substitute("<p>Cost of goods sold moved against the prior period.</p>", FactSet([]))
        assert find_ungrounded_quantity_words(rendered) == []
