"""The tri-state applicability engine.

These tests exist because the difference between "no" and "nobody asked" is the
whole safety property of this build. A two-state engine passes every test in
this file except the ones that matter.
"""
from __future__ import annotations

import pytest

from real_estate_pack.conditions import (
    ConditionError,
    Tri,
    evaluate,
    referenced_fields,
)
from real_estate_pack.models import UNSET


class Facts:
    """Minimal stand-in for the fact source the engine reads."""

    def __init__(self, **values):
        self.values = values

    def lookup_fact(self, name):
        value = self.values.get(name, UNSET)
        return UNSET if value is None else value


# --------------------------------------------------------------- the core rule


def test_missing_fact_is_undetermined_not_false():
    """The single most important assertion in this project.

    If this ever returns FALSE, a federally required lead-paint disclosure
    silently disappears from a pre-1978 lease and nothing in the output looks
    wrong."""
    result = evaluate({"field": "year_built", "op": "lt", "value": 1978}, Facts())
    assert result.state == Tri.UNDETERMINED
    assert not result.applies
    assert result.missing_facts == ("year_built",)


def test_undetermined_names_the_fact_so_the_user_can_answer_it():
    condition = {"all": [
        {"field": "sprinkler_system_present", "op": "is_true"},
        {"field": "storeys_in_building", "op": "gt", "value": 3},
    ]}
    result = evaluate(condition, Facts())
    assert set(result.missing_facts) == {"sprinkler_system_present", "storeys_in_building"}


def test_explicit_false_is_a_real_answer_and_switches_the_rule_off():
    result = evaluate({"field": "flooded_in_last_5_years", "op": "is_true"},
                      Facts(flooded_in_last_5_years=False))
    assert result.state == Tri.FALSE
    assert result.missing_facts == ()


# ------------------------------------------------------------ combinator logic


def test_all_short_circuits_on_definite_false_without_demanding_siblings():
    """A California rule mentioning bed bugs must not make a Texas property
    demand a bed bug history. A definite FALSE anywhere in an AND settles it."""
    condition = {"all": [
        {"field": "state", "op": "eq", "value": "CA"},
        {"field": "bed_bug_history", "op": "is_true"},
    ]}
    result = evaluate(condition, Facts(state="TX"))
    assert result.state == Tri.FALSE
    assert result.missing_facts == ()


def test_all_is_undetermined_when_a_clause_is_unanswerable_and_none_are_false():
    condition = {"all": [
        {"field": "state", "op": "eq", "value": "CA"},
        {"field": "bed_bug_history", "op": "is_true"},
    ]}
    result = evaluate(condition, Facts(state="CA"))
    assert result.state == Tri.UNDETERMINED
    assert result.missing_facts == ("bed_bug_history",)


def test_any_short_circuits_on_definite_true():
    condition = {"any": [
        {"field": "in_special_flood_hazard_area", "op": "is_true"},
        {"field": "in_area_of_potential_flooding", "op": "is_true"},
    ]}
    result = evaluate(condition, Facts(in_special_flood_hazard_area=True))
    assert result.state == Tri.TRUE


def test_any_with_one_false_and_one_unknown_is_undetermined():
    """The real California flood case. One 'no' does not settle an OR — the
    disclosure could still be required by the unanswered half."""
    condition = {"any": [
        {"field": "in_special_flood_hazard_area", "op": "is_true"},
        {"field": "in_area_of_potential_flooding", "op": "is_true"},
    ]}
    result = evaluate(condition, Facts(in_special_flood_hazard_area=False))
    assert result.state == Tri.UNDETERMINED
    assert result.missing_facts == ("in_area_of_potential_flooding",)


def test_any_with_all_false_is_false():
    condition = {"any": [
        {"field": "a", "op": "is_true"},
        {"field": "b", "op": "is_true"},
    ]}
    assert evaluate(condition, Facts(a=False, b=False)).state == Tri.FALSE


def test_not_inverts_definite_values_but_preserves_undetermined():
    assert evaluate({"not": {"field": "a", "op": "is_true"}}, Facts(a=True)).state == Tri.FALSE
    assert evaluate({"not": {"field": "a", "op": "is_true"}}, Facts(a=False)).state == Tri.TRUE
    undetermined = evaluate({"not": {"field": "a", "op": "is_true"}}, Facts())
    assert undetermined.state == Tri.UNDETERMINED
    assert undetermined.missing_facts == ("a",)


def test_duplicate_missing_facts_are_reported_once():
    condition = {"all": [
        {"field": "a", "op": "gt", "value": 1},
        {"field": "a", "op": "lt", "value": 9},
    ]}
    assert evaluate(condition, Facts()).missing_facts == ("a",)


# -------------------------------------------------------------------- operators


@pytest.mark.parametrize(
    "op,actual,expected,want",
    [
        ("eq", "CA", "CA", True),
        ("eq", "ca", "CA", True),          # case-insensitive string compare
        ("ne", "TX", "CA", True),
        ("lt", 1955, 1978, True),
        ("lt", 1985, 1978, False),
        ("lte", 1978, 1978, True),
        ("gt", 12, 3, True),
        ("gte", 2, 2, True),
        ("in", "condo", ["condo", "apartment"], True),
        ("not_in", "duplex", ["condo", "apartment"], True),
        ("is_true", True, None, True),
        ("is_false", False, None, True),
    ],
)
def test_operator_table(op, actual, expected, want):
    condition = {"field": "f", "op": op}
    if expected is not None:
        condition["value"] = expected
    assert evaluate(condition, Facts(f=actual)).applies is want


def test_is_true_does_not_accept_truthy_non_booleans():
    """A property_type of 'condo' is truthy in Python but is not an answer to a
    yes/no compliance question."""
    assert evaluate({"field": "f", "op": "is_true"}, Facts(f="condo")).state == Tri.FALSE
    assert evaluate({"field": "f", "op": "is_true"}, Facts(f=1)).state == Tri.FALSE


def test_is_set_is_answerable_even_when_the_fact_is_absent():
    """`is_set` asks 'was this supplied', which is always answerable. Texas and
    New York rely on it for notices required in BOTH directions."""
    assert evaluate({"field": "f", "op": "is_set"}, Facts()).state == Tri.FALSE
    assert evaluate({"field": "f", "op": "is_set"}, Facts(f=False)).state == Tri.TRUE


def test_unknown_operator_raises_rather_than_being_skipped():
    """A typo must not silently decide that a legal requirement does not apply."""
    with pytest.raises(ConditionError, match="Unknown operator"):
        evaluate({"field": "f", "op": "approximately"}, Facts(f=1))


def test_missing_field_or_op_raises():
    with pytest.raises(ConditionError, match="missing a 'field'"):
        evaluate({"op": "is_true"}, Facts())
    with pytest.raises(ConditionError, match="missing an 'op'"):
        evaluate({"field": "f"}, Facts())


def test_non_mapping_condition_raises():
    with pytest.raises(ConditionError, match="must be a mapping"):
        evaluate(["field", "f"], Facts())


def test_all_and_any_require_lists():
    with pytest.raises(ConditionError, match="'all' expects a list"):
        evaluate({"all": {"field": "f", "op": "is_true"}}, Facts())
    with pytest.raises(ConditionError, match="'any' expects a list"):
        evaluate({"any": {"field": "f", "op": "is_true"}}, Facts())


def test_numeric_comparison_against_non_numeric_raises():
    with pytest.raises(ConditionError, match="numerically"):
        evaluate({"field": "f", "op": "lt", "value": 1978}, Facts(f="unknown"))


def test_in_operator_requires_a_list():
    with pytest.raises(ConditionError, match="expects a list"):
        evaluate({"field": "f", "op": "in", "value": "condo"}, Facts(f="condo"))


# ------------------------------------------------------------------- unconditional


def test_absent_condition_means_the_rule_always_applies():
    """Megan's Law and the radon notice have no precondition. Unconditional is
    the safe reading of 'no stated condition'."""
    assert evaluate(None, Facts()).state == Tri.TRUE


# ----------------------------------------------------------- field introspection


def test_referenced_fields_walks_nested_conditions():
    condition = {"all": [
        {"field": "a", "op": "is_true"},
        {"any": [{"field": "b", "op": "is_true"}, {"not": {"field": "c", "op": "is_true"}}]},
    ]}
    assert referenced_fields(condition) == ["a", "b", "c"]


def test_referenced_fields_of_none_is_empty():
    assert referenced_fields(None) == []
