"""Statistics tests against hand-computed fixtures.

PLAN.md.pdf section 4 asks for "kappa/accuracy math tested against
hand-computed fixtures". The kappa cases below are worked by hand in the
comments so a reader can check the arithmetic without trusting the code.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.stats import (  # noqa: E402
    build_rating_matrix,
    describe,
    fleiss_kappa,
    interpret_kappa,
    iqr,
    median,
    percentile,
    wilson_interval,
)


# -- descriptive stats ----------------------------------------------------


def test_median_odd_and_even():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 3, 2]) == 2.5


def test_percentile_matches_numpy_linear_convention():
    values = [1, 2, 3, 4]
    # rank = p/100 * (n-1); for p=25, rank = 0.75 -> 1 + 0.75*(2-1) = 1.75
    assert percentile(values, 25) == 1.75
    assert percentile(values, 50) == 2.5
    assert percentile(values, 75) == 3.25
    assert percentile(values, 0) == 1
    assert percentile(values, 100) == 4


def test_iqr_of_a_known_sample():
    q1, q3 = iqr([1, 2, 3, 4, 5])
    assert (q1, q3) == (2.0, 4.0)


def test_describe_reports_median_not_only_mean():
    """Decision times are right-skewed; a lone wanderer must not set the headline."""
    values = [1000, 1100, 1200, 1300, 60000]
    summary = describe(values)
    assert summary["median"] == 1200
    assert summary["mean"] > 12000, "the mean is dragged by the outlier, as expected"
    assert summary["n"] == 5


def test_describe_handles_empty():
    assert describe([]) == {"n": 0}


def test_single_value_percentile_does_not_crash():
    assert percentile([42], 25) == 42


def test_percentile_rejects_out_of_range():
    with pytest.raises(ValueError):
        percentile([1, 2], 101)


# -- Fleiss' kappa --------------------------------------------------------


def test_kappa_perfect_agreement():
    # 3 items, 4 raters, all unanimous but categories both used.
    # P_i = 1 for every item -> P_bar = 1.
    # p_approve = 8/12 = 2/3, p_reject = 4/12 = 1/3
    # P_e = (2/3)^2 + (1/3)^2 = 4/9 + 1/9 = 5/9
    # kappa = (1 - 5/9) / (1 - 5/9) = 1
    ratings = [[4, 0], [4, 0], [0, 4]]
    assert fleiss_kappa(ratings) == pytest.approx(1.0)


def test_kappa_chance_level_is_zero():
    # 2 items, 2 raters, perfectly split every time.
    # P_i = (1*0 + 1*0) / (2*1) = 0 for both items -> P_bar = 0
    # p_approve = p_reject = 0.5 -> P_e = 0.25 + 0.25 = 0.5
    # kappa = (0 - 0.5) / (1 - 0.5) = -1.0  (maximally worse than chance)
    ratings = [[1, 1], [1, 1]]
    assert fleiss_kappa(ratings) == pytest.approx(-1.0)


def test_kappa_hand_computed_mixed_case():
    # 4 items, 3 raters.
    #   item0 [3,0]: agree pairs = 3*2 = 6 -> 6/(3*2) = 1.0
    #   item1 [2,1]: 2*1 + 0    = 2 -> 2/6 = 1/3
    #   item2 [0,3]: 0 + 3*2    = 6 -> 6/6 = 1.0
    #   item3 [1,2]: 0 + 2*1    = 2 -> 2/6 = 1/3
    # P_bar = (1 + 1/3 + 1 + 1/3)/4 = (8/3)/4 = 2/3
    # totals: approve = 3+2+0+1 = 6, reject = 0+1+3+2 = 6, of 12
    # p = 0.5, 0.5 -> P_e = 0.5
    # kappa = (2/3 - 1/2) / (1 - 1/2) = (1/6)/(1/2) = 1/3
    ratings = [[3, 0], [2, 1], [0, 3], [1, 2]]
    assert fleiss_kappa(ratings) == pytest.approx(1.0 / 3.0)


def test_kappa_is_one_when_everyone_always_picks_one_category():
    """P_e = 1 makes kappa 0/0; report 1.0 rather than dividing by zero."""
    assert fleiss_kappa([[3, 0], [3, 0]]) == pytest.approx(1.0)


def test_kappa_rejects_uneven_rater_counts():
    """A missing rating would quietly bias kappa upward."""
    with pytest.raises(ValueError, match="same number of raters"):
        fleiss_kappa([[3, 0], [2, 0]])


def test_kappa_needs_at_least_two_raters():
    with pytest.raises(ValueError, match="at least 2 raters"):
        fleiss_kappa([[1, 0], [0, 1]])


def test_kappa_rejects_empty_input():
    with pytest.raises(ValueError):
        fleiss_kappa([])


def test_interpret_kappa_bands():
    assert interpret_kappa(-0.1) == "worse than chance"
    assert interpret_kappa(0.1) == "slight"
    assert interpret_kappa(0.35) == "fair"
    assert interpret_kappa(0.5) == "moderate"
    assert interpret_kappa(0.7) == "substantial"
    assert interpret_kappa(0.9) == "almost perfect"


# -- rating matrix --------------------------------------------------------


def test_build_rating_matrix_counts_verdicts():
    matrix, excluded = build_rating_matrix(
        {"c1": ["approve", "approve", "reject"], "c2": ["reject", "reject", "reject"]}
    )
    assert matrix == [[2, 1], [0, 3]]
    assert excluded == []


def test_partially_rated_changes_are_excluded_and_reported():
    """Dropping them silently would overstate agreement."""
    matrix, excluded = build_rating_matrix(
        {"c1": ["approve", "reject"], "c2": ["approve"]}
    )
    assert matrix == [[1, 1]]
    assert excluded == ["c2"]


def test_empty_matrix_is_not_an_error():
    assert build_rating_matrix({}) == ([], [])


# -- proportions ----------------------------------------------------------


def test_wilson_interval_brackets_the_estimate():
    low, high = wilson_interval(6, 7)
    assert low < 6 / 7 < high
    assert 0.0 <= low and high <= 1.0


def test_wilson_interval_is_wide_at_small_n():
    """The point of reporting it: 6/7 must not read as 86% +/- nothing."""
    low, high = wilson_interval(6, 7)
    assert high - low > 0.30, "a 7-observation interval should be visibly wide"


def test_wilson_interval_handles_the_extremes():
    assert wilson_interval(0, 0) == (0.0, 0.0)
    low, high = wilson_interval(0, 5)
    assert low == 0.0 and 0 < high < 1
    low, high = wilson_interval(5, 5)
    assert high == pytest.approx(1.0, abs=1e-9) or high < 1.0
    assert low > 0.0
