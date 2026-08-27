"""Fact extraction: the numbers must come from the cells, exactly."""

from decimal import Decimal

import pytest

from narrative_report.facts import (
    RangeParseError,
    column_letter,
    derive_facts,
    parse_cell,
    read_table,
)
from narrative_report.numbers import format_fact

# A shape a finance team would actually select: periods across, line items down,
# mixed notation including parenthesised negatives and a blank.
PNL = [
    ["Line item", "Q1", "Q2", "Q3", "Q4"],
    ["Revenue", "$1,200,000", "$1,320,000", "$1,180,000", "$1,455,000"],
    ["COGS", "(480,000)", "(528,000)", "(472,000)", "(560,000)"],
    ["Gross profit", "$720,000", "$792,000", "$708,000", "$895,000"],
    ["", "", "", "", ""],
    ["Headcount", "42", "44", "44", "51"],
    ["Churn", "2.4%", "2.1%", "3.9%", "1.8%"],
    ["Notes", "steady", "up", "dip", "record"],
]


@pytest.fixture
def table():
    return read_table(PNL, sheet="P&L", a1="B2:F9")


class TestCellParsing:
    @pytest.mark.parametrize(
        "raw,value,unit",
        [
            ("$1,200,000", Decimal("1200000"), "currency"),
            ("(480,000)", Decimal("-480000"), None),
            ("($480,000)", Decimal("-480000"), "currency"),
            ("2.4%", Decimal("2.4"), "percent"),
            ("42", Decimal("42"), None),
            ("-17.5", Decimal("-17.5"), None),
            ("€980", Decimal("980"), "currency"),
            ("", None, None),
            ("   ", None, None),
            ("steady", None, None),
            ("#DIV/0!", None, None),
            (None, None, None),
        ],
    )
    def test_parses_finance_notation(self, raw, value, unit):
        assert parse_cell(raw) == (value, unit)

    def test_column_letters(self):
        assert [column_letter(i) for i in (0, 25, 26, 27, 51)] == ["A", "Z", "AA", "AB", "AZ"]


class TestTableReading:
    def test_reads_periods_and_series(self, table):
        assert table.periods == ["Q1", "Q2", "Q3", "Q4"]
        assert [s.label for s in table.series] == [
            "Revenue",
            "COGS",
            "Gross profit",
            "Headcount",
            "Churn",
        ]

    def test_text_only_and_blank_rows_are_skipped(self, table):
        # "Notes" holds words, not data; it must not become a series.
        assert "Notes" not in [s.label for s in table.series]

    def test_units_are_inferred_per_row(self, table):
        units = {s.label: s.unit for s in table.series}
        assert units["Revenue"] == "currency"
        assert units["Churn"] == "percent"
        assert units["Headcount"] == "number"

    def test_provenance_is_real_a1_notation(self, table):
        revenue = next(s for s in table.series if s.label == "Revenue")
        # Selection starts at B2, so the header is row 2 and Revenue is row 3,
        # spanning the four period columns C..F.
        assert revenue.row_a1 == "P&L!C3:F3"

    def test_rejects_a_selection_with_no_data(self):
        with pytest.raises(RangeParseError, match="header row and at least one data row"):
            read_table([["Line item", "Q1"]], sheet="S", a1="A1:B1")

    def test_rejects_a_selection_with_no_numbers(self):
        with pytest.raises(RangeParseError, match="no numeric rows"):
            read_table(
                [["Item", "Q1"], ["Notes", "hello"], ["More", "world"]], sheet="S", a1="A1:B3"
            )


class TestDerivedFacts:
    def test_totals_match_the_cells_exactly(self, table):
        facts = derive_facts(table)
        # 1,200,000 + 1,320,000 + 1,180,000 + 1,455,000
        assert facts["series.revenue.total"].value == Decimal("5155000")
        assert format_fact(facts["series.revenue.total"]) == "$5,155,000"

    def test_period_over_period_change(self, table):
        facts = derive_facts(table)
        assert facts["series.revenue.delta_abs"].value == Decimal("275000")
        assert format_fact(facts["series.revenue.delta_abs"]) == "+$275,000"
        # 275,000 / 1,180,000 = 23.305...%
        assert format_fact(facts["series.revenue.delta_pct"]) == "+23.3%"

    def test_direction_is_a_word_not_a_number(self, table):
        facts = derive_facts(table)
        assert facts["series.revenue.direction"].value == "increased"
        assert facts["series.churn.direction"].value == "decreased"

    def test_peak_and_its_period(self, table):
        facts = derive_facts(table)
        assert format_fact(facts["series.headcount.peak"]) == "51"
        assert facts["series.headcount.peak_period"].value == "Q4"

    def test_top_mover_is_the_largest_proportional_move(self, table):
        facts = derive_facts(table)
        # Churn 3.9 -> 1.8 is -53.8%, larger in magnitude than revenue's +23.3%.
        assert facts["top_mover.name"].value == "Churn"
        assert format_fact(facts["top_mover.delta_pct"]) == "-53.8%"

    def test_every_fact_carries_provenance(self, table):
        for fact in derive_facts(table).values():
            assert fact.provenance, f"{fact.key} has no provenance"

    def test_extraction_is_deterministic(self, table):
        assert derive_facts(table).digests() == derive_facts(table).digests()

    def test_growth_from_zero_yields_no_percentage_fact(self):
        t = read_table(
            [["Item", "Q1", "Q2"], ["New line", "0", "5000"]], sheet="S", a1="A1:C2"
        )
        facts = derive_facts(t)
        # A move off zero is not a percentage. Refusing to compute it is the
        # point: the narrative has to say it in words instead.
        assert "series.new_line.delta_pct" not in facts
        assert "series.new_line.delta_abs" in facts
        assert facts["series.new_line.direction"].value == "increased"

    def test_share_of_total_only_applies_to_currency(self, table):
        facts = derive_facts(table)
        assert "series.revenue.share_latest" in facts
        assert "series.headcount.share_latest" not in facts
