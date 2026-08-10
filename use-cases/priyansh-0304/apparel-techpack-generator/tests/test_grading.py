"""Tests for deterministic size grading — the core correctness guarantee
of this build. No API involved; pure arithmetic."""

import pytest
from techpack.grading import grade_measurement, build_graded_spec, SIZE_ORDER


SAMPLE_STYLE = {
    "base_size": "M",
    "size_range": ["XS", "S", "M", "L", "XL", "XXL"],
    "measurement_points": [
        {"point_name": "Chest Width", "base_value": 20.0, "grade_rule": 1.0, "tolerance": 0.5},
        {"point_name": "Neck Width", "base_value": 7.0, "grade_rule": 0.125, "tolerance": 0.125},
    ],
}


def test_base_size_returns_exact_base_value():
    # Grading at the base size should never drift from the source value
    assert grade_measurement(20.0, 1.0, "M", "M") == 20.0


def test_grades_up_correctly():
    # L is one step above base M -> +1 grade rule
    assert grade_measurement(20.0, 1.0, "M", "L") == 21.0
    # XXL is three steps above M -> +3 grade rules
    assert grade_measurement(20.0, 1.0, "M", "XXL") == 23.0


def test_grades_down_correctly():
    # XS is two steps below base M -> -2 grade rules
    assert grade_measurement(20.0, 1.0, "M", "XS") == 18.0


def test_small_grade_rule_precision():
    # Neck width grades slowly (0.125"/size) — checks fractional grading works
    assert grade_measurement(7.0, 0.125, "M", "L") == 7.125
    assert grade_measurement(7.0, 0.125, "M", "XS") == 6.75


def test_zero_grade_rule_never_changes_across_sizes():
    # A point that shouldn't grade at all (grade_rule=0) must stay constant
    for size in SIZE_ORDER:
        assert grade_measurement(5.0, 0.0, "M", size) == 5.0


def test_build_graded_spec_covers_every_point_and_size():
    table = build_graded_spec(SAMPLE_STYLE)

    assert set(table.keys()) == {"Chest Width", "Neck Width"}
    for point_name in table:
        assert set(table[point_name].keys()) == set(SAMPLE_STYLE["size_range"])


def test_build_graded_spec_matches_manual_calculation():
    table = build_graded_spec(SAMPLE_STYLE)

    # Manually verify a few values independently of the grading function itself
    assert table["Chest Width"]["M"] == 20.0
    assert table["Chest Width"]["XXL"] == 23.0
    assert table["Chest Width"]["XS"] == 18.0
    assert table["Neck Width"]["L"] == 7.125


def test_different_base_size_still_grades_correctly():
    # Sanity check: grading logic isn't hardcoded to assume M is always base
    style = {**SAMPLE_STYLE, "base_size": "S"}
    table = build_graded_spec(style)

    # Now M is one step above the S base
    assert table["Chest Width"]["S"] == 20.0
    assert table["Chest Width"]["M"] == 21.0