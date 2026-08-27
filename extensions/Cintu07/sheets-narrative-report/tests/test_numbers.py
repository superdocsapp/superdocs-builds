"""The invariant this build sells: prose cannot contain an untraceable number.

Every test here is a statement about what the system must *never* do.
"""

from decimal import Decimal

import pytest

from narrative_report.models import Fact, FactSet
from narrative_report.numbers import (
    NumericIntegrityError,
    assert_clean,
    find_ungrounded_quantity_words,
    find_unverified_numerals,
    format_fact,
    referenced_keys,
    substitute,
)


def f(key, value, fmt="number0", unit="number", label="", prov="Sheet1!A1"):
    return Fact(
        key=key,
        value=Decimal(value) if unit != "text" else value,
        unit=unit,
        label=label or key,
        provenance=prov,
        fmt=fmt,
    )


@pytest.fixture
def facts():
    return FactSet(
        [
            f("rev.total", "1234567.4", "currency0", label="Total revenue"),
            f("rev.growth", "12.34", "signed_percent1", "percent", label="Revenue growth"),
            f("margin", "41.6", "percent1", "percent", label="Gross margin"),
            f("period", "Q3 FY24", "text", "text", label="Period"),
            f("headcount", "48", "number0", label="Headcount"),
        ]
    )


class TestFormatting:
    @pytest.mark.parametrize(
        "value,fmt,expected",
        [
            ("1234567.4", "currency0", "$1,234,567"),
            ("1234567.5", "currency0", "$1,234,568"),  # half-up, not banker's
            ("-980.2", "currency0", "-$980"),
            ("1234.567", "currency2", "$1,234.57"),
            ("12.34", "signed_percent1", "+12.3%"),
            ("-4.04", "signed_percent1", "-4.0%"),
            ("-0.01", "signed_percent1", "+0.0%"),  # negative zero must not print "-0.0"
            ("1500", "signed_currency0", "+$1,500"),
            ("1.44", "multiple1", "1.4x"),
            ("0", "number0", "0"),
        ],
    )
    def test_renders_expected_string(self, value, fmt, expected):
        assert format_fact(f("k", value, fmt)) == expected

    def test_float_values_are_rejected_at_construction(self):
        # Cents lost to binary floating point is a correctness bug, not a style one.
        with pytest.raises(TypeError, match="Decimal"):
            Fact(key="k", value=1234.56, unit="currency", label="l", provenance="p")

    def test_formatting_is_stable_across_calls(self, facts):
        # Byte-identical re-render is what the incremental guarantee stands on.
        assert format_fact(facts["rev.total"]) == format_fact(facts["rev.total"])


class TestSubstitution:
    def test_replaces_tokens_and_records_spans(self, facts):
        r = substitute("Revenue reached {{fact:rev.total}} in {{fact:period}}.", facts)
        assert r.text == "Revenue reached $1,234,567 in Q3 FY24."
        assert r.used_keys == ["rev.total", "period"]
        for lo, hi in r.spans:
            assert r.text[lo:hi] in ("$1,234,567", "Q3 FY24")

    def test_unknown_token_is_preserved_not_dropped(self, facts):
        r = substitute("Revenue was {{fact:nope.missing}}.", facts)
        assert "{{fact:nope.missing}}" in r.text
        assert r.unknown_tokens == ["nope.missing"]

    def test_repeated_token_gets_a_span_each_time(self, facts):
        r = substitute("{{fact:headcount}} and {{fact:headcount}}", facts)
        assert len(r.spans) == 2
        assert r.text == "48 and 48"

    def test_referenced_keys_are_deduped_in_order(self):
        keys = referenced_keys("{{fact:b}} {{fact:a}} {{fact:b}}")
        assert keys == ("b", "a")


class TestIntegrityCheck:
    def test_clean_prose_passes(self, facts):
        r = substitute(
            "<p>Revenue reached {{fact:rev.total}}, up {{fact:rev.growth}}.</p>", facts
        )
        assert find_unverified_numerals(r) == []
        assert_clean(r)

    def test_model_typed_number_is_caught(self, facts):
        # The exact failure this build exists to prevent.
        r = substitute("<p>Revenue reached about 4.2 million this quarter.</p>", facts)
        violations = find_unverified_numerals(r)
        assert [v.text for v in violations] == ["4.2"]
        with pytest.raises(NumericIntegrityError, match="4.2"):
            assert_clean(r)

    def test_number_adjacent_to_a_real_fact_is_still_caught(self, facts):
        r = substitute("<p>{{fact:rev.total}} across 4 regions.</p>", facts)
        assert [v.text for v in find_unverified_numerals(r)] == ["4"]

    def test_digits_inside_markup_are_ignored(self, facts):
        r = substitute(
            '<p data-chunk-id="0b1953b9-c95b-4f1e-ba36" style="width:600px">'
            "Revenue reached {{fact:rev.total}}.</p>",
            facts,
        )
        assert find_unverified_numerals(r) == []

    def test_html_entities_are_ignored(self, facts):
        r = substitute("<p>Revenue &#8212; {{fact:rev.total}} &mdash; held.</p>", facts)
        assert find_unverified_numerals(r) == []

    def test_partial_overlap_with_a_fact_span_is_not_a_free_pass(self, facts):
        # A model appending digits onto a substituted value must not slip through.
        r = substitute("<p>{{fact:headcount}}9 staff.</p>", facts)
        assert [v.text for v in find_unverified_numerals(r)] == ["489"]

    def test_unresolved_token_fails_the_gate(self, facts):
        r = substitute("<p>Revenue was {{fact:ghost}}.</p>", facts)
        with pytest.raises(NumericIntegrityError, match="unresolved fact tokens"):
            assert_clean(r)

    def test_year_written_by_the_model_is_flagged(self, facts):
        # Deliberate: years are facts too. Forcing them through the fact table is
        # what keeps "in 2023" from drifting to "in 2024" on a later run.
        r = substitute("<p>Revenue in 2024 reached {{fact:rev.total}}.</p>", facts)
        assert [v.text for v in find_unverified_numerals(r)] == ["2024"]

    def test_sentence_final_decimal_does_not_overrun_its_span(self):
        # Regression: a greedy digit-run regex swallowed the full stop after
        # "$1,234.57." and reported the whole run as untraceable.
        one = FactSet([f("v", "1234.567", "currency2")])
        r = substitute("<p>Total was {{fact:v}}.</p>", one)
        assert r.text == "<p>Total was $1,234.57.</p>"
        assert find_unverified_numerals(r) == []


class TestUngroundedQuantityWords:
    """Words that grade the data are claims too, and must come from a fact.

    Found in a live run: the model wrote "revenue increased materially", taking
    the verb from a fact but typing the adverb itself. The number was correct,
    but "materially" was the model's own judgement, and because it is not tied
    to any fact the incremental planner would never refresh it. A later quarter
    could reduce the move to half a percent and the word would still say
    materially.
    """

    def test_a_typed_size_word_is_reported(self, facts):
        r = substitute("<p>Revenue rose materially to {{fact:rev.total}}.</p>", facts)
        assert [v.text for v in find_ungrounded_quantity_words(r)] == ["materially"]

    def test_a_size_word_that_came_from_a_fact_is_accepted(self):
        graded = FactSet([f("band", "moved sharply", "text", "text")])
        r = substitute("<p>Revenue {{fact:band}} this quarter.</p>", graded)
        assert find_ungrounded_quantity_words(r) == []

    @pytest.mark.parametrize(
        "word", ["sharply", "roughly", "about", "nearly", "surged", "doubled", "significantly"]
    )
    def test_common_hedges_and_intensifiers_are_caught(self, word, facts):
        r = substitute(f"<p>Revenue {word} reached {{{{fact:rev.total}}}}.</p>", facts)
        assert [v.text for v in find_ungrounded_quantity_words(r)] == [word]

    def test_ordinary_prose_is_left_alone(self, facts):
        r = substitute(
            "<p>Revenue reached {{fact:rev.total}} in {{fact:period}}, ahead of "
            "the prior period.</p>",
            facts,
        )
        assert find_ungrounded_quantity_words(r) == []

    def test_a_pattern_claim_is_no_longer_treated_as_ordinary_prose(self, facts):
        """This test used to assert the opposite, and it was wrong.

        "the fourth consecutive quarter of growth" reads like harmless prose,
        which is exactly why it slipped through: the figures around it are
        grounded, so the sentence looks checked. The claim that the growth ran
        for four quarters was never verified against anything. It is a claim
        about the data and it needs a fact behind it, like any other.
        """
        r = substitute(
            "<p>Revenue reached {{fact:rev.total}} in {{fact:period}}, the fourth "
            "consecutive quarter of growth.</p>",
            facts,
        )
        assert [v.text for v in find_ungrounded_quantity_words(r)] == ["consecutive"]

    def test_words_inside_markup_are_ignored(self, facts):
        r = substitute('<p class="materially-wide">{{fact:rev.total}}</p>', facts)
        assert find_ungrounded_quantity_words(r) == []

    def test_it_does_not_block_the_hard_gate(self, facts):
        # Ungrounded adjectives are a warning, not a failure. assert_clean is
        # about figures, and must not start rejecting judgement calls.
        r = substitute("<p>Revenue rose sharply to {{fact:rev.total}}.</p>", facts)
        assert_clean(r)
