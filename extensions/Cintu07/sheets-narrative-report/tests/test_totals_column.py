"""A trailing totals column is not a period.

Found against the live API: a selection ending in "FY total" made the total the
"latest period", so every period-over-period figure compared Q4 against the
year, producing confident nonsense like "+313%". Finance users select the
totals column constantly, so this is a correctness requirement, not a nicety.
"""

from decimal import Decimal

import pytest

from narrative_report.facts import derive_facts, read_table
from narrative_report.numbers import format_fact

WITH_TOTAL = [
    ["Line item", "Q1", "Q2", "Q3", "Q4", "FY total"],
    ["Revenue", "$1,000", "$1,100", "$1,200", "$1,300", "$4,600"],
    ["Costs", "$400", "$420", "$440", "$460", "$1,720"],
    ["Headcount", "10", "11", "12", "13", "13"],
]


class TestDetection:
    def test_labelled_total_column_is_excluded_from_periods(self):
        table = read_table(WITH_TOTAL, sheet="P&L", a1="A1:F4")
        assert table.periods == ["Q1", "Q2", "Q3", "Q4"]
        assert table.total_label == "FY total"

    def test_period_over_period_compares_real_periods(self):
        facts = derive_facts(read_table(WITH_TOTAL, sheet="P&L", a1="A1:F4"))
        # Q4 vs Q3: 1300 - 1200 = +100, +8.3%, not Q4 vs the year total.
        assert facts["series.revenue.latest"].value == Decimal("1300")
        assert format_fact(facts["series.revenue.delta_abs"]) == "+$100"
        assert format_fact(facts["series.revenue.delta_pct"]) == "+8.3%"

    def test_computed_total_uses_only_the_periods(self):
        facts = derive_facts(read_table(WITH_TOTAL, sheet="P&L", a1="A1:F4"))
        assert facts["series.revenue.total"].value == Decimal("4600")

    @pytest.mark.parametrize("header", ["Total", "TOTAL", "YTD", "FY", "Cumulative", "Full year"])
    def test_common_total_headers_are_recognised(self, header):
        rows = [r[:] for r in WITH_TOTAL]
        rows[0][-1] = header
        assert read_table(rows, sheet="S", a1="A1:F4").total_label == header

    def test_unlabelled_total_is_caught_by_arithmetic(self):
        # Header gives nothing away; the column is still the sum of the others.
        rows = [r[:] for r in WITH_TOTAL]
        rows[0][-1] = "FY24"
        table = read_table(rows, sheet="S", a1="A1:F4")
        assert table.periods == ["Q1", "Q2", "Q3", "Q4"]

    def test_an_ordinary_final_period_is_left_alone(self):
        rows = [
            ["Item", "Q1", "Q2", "Q3", "Q4"],
            ["Revenue", "1000", "1100", "1200", "1300"],
            ["Costs", "400", "420", "440", "460"],
        ]
        table = read_table(rows, sheet="S", a1="A1:E3")
        assert table.periods == ["Q1", "Q2", "Q3", "Q4"]
        assert table.total_label is None

    def test_two_column_selection_is_never_stripped(self):
        # Too few columns to distinguish; removing one would leave nothing.
        rows = [["Item", "Q1", "Total"], ["Revenue", "1000", "1000"]]
        table = read_table(rows, sheet="S", a1="A1:C2")
        assert table.total_label is None
        assert len(table.periods) == 2


class TestStatedTotalConflicts:
    def test_a_wrong_stated_total_is_surfaced(self):
        rows = [r[:] for r in WITH_TOTAL]
        rows[1][-1] = "$9,999"  # sheet claims a total its own periods do not support
        table = read_table(rows, sheet="P&L", a1="A1:F4")
        assert table.total_conflicts
        assert "Revenue" in table.total_conflicts[0]
        assert "P&L!B2:E2" in table.total_conflicts[0]

    def test_a_correct_stated_total_raises_nothing(self):
        table = read_table(WITH_TOTAL, sheet="P&L", a1="A1:F4")
        assert table.total_conflicts == []

    def test_a_closing_balance_total_is_not_a_conflict(self):
        # Headcount's "FY total" of 13 is the closing headcount, not the sum of
        # four quarters. Flagging it would be a false positive on a very common
        # sheet shape, and false alarms are how a findings list gets ignored.
        table = read_table(WITH_TOTAL, sheet="P&L", a1="A1:F4")
        assert not any("Headcount" in c for c in table.total_conflicts)

    def test_a_total_matching_neither_reading_is_flagged(self):
        rows = [r[:] for r in WITH_TOTAL]
        rows[3][-1] = "77"  # not the sum (46) and not the closing value (13)
        table = read_table(rows, sheet="P&L", a1="A1:F4")
        assert any("Headcount" in c for c in table.total_conflicts)

    def test_the_stated_total_is_kept_for_reference(self):
        table = read_table(WITH_TOTAL, sheet="P&L", a1="A1:F4")
        revenue = next(s for s in table.series if s.label == "Revenue")
        assert revenue.stated_total == Decimal("4600")

    def test_conflict_is_reported_not_reconciled(self):
        # The report must never quietly pick one number over the other.
        rows = [r[:] for r in WITH_TOTAL]
        rows[1][-1] = "$9,999"
        table = read_table(rows, sheet="P&L", a1="A1:F4")
        facts = derive_facts(table)
        assert facts["series.revenue.total"].value == Decimal("4600")  # computed, not stated
        assert any("9,999" in c for c in table.total_conflicts)
