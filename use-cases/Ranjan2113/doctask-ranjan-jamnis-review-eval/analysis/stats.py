"""Statistics for the study. Pure functions, no I/O, no dependencies.

Kept separate from analyze.py so the maths can be tested against
hand-computed fixtures (PLAN.md.pdf section 4 asks for exactly that).

No numpy/scipy: the whole dataset is a handful of reviewers times a few dozen
changes, and a dependency-free module is one fewer thing between a reader and
the arithmetic.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence


def median(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("median of an empty sequence")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile (the 'inclusive' convention).

    Matches numpy's default so anyone re-running this with numpy gets the same
    numbers.
    """
    if not values:
        raise ValueError("percentile of an empty sequence")
    if not 0.0 <= p <= 100.0:
        raise ValueError(f"percentile out of range: {p}")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[int(rank)])
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def iqr(values: Sequence[float]) -> tuple[float, float]:
    """Interquartile range as (q1, q3).

    PLAN.md.pdf section 7 asks for median + IQR rather than mean: decision
    times are right-skewed (one reviewer who wanders off drags a mean badly),
    and with N this small a single outlier would dominate.
    """
    return percentile(values, 25), percentile(values, 75)


def describe(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    q1, q3 = iqr(values)
    return {
        "n": len(values),
        "median": median(values),
        "q1": q1,
        "q3": q3,
        "min": float(min(values)),
        "max": float(max(values)),
        "mean": sum(values) / len(values),
    }


def fleiss_kappa(ratings: Sequence[Sequence[int]]) -> float:
    """Fleiss' kappa for n items rated by a fixed number of raters.

    `ratings[i][j]` = how many raters assigned item i to category j. Every row
    must sum to the same number of raters.

    Returns agreement above chance: 1.0 is perfect, 0.0 is chance-level, and
    negative means raters agreed *less* than chance would predict.

    Raises on ragged input rather than silently rescaling, because a row with a
    missing rating would quietly bias kappa upward.
    """
    if not ratings:
        raise ValueError("no items to score")

    n_raters = sum(ratings[0])
    if n_raters < 2:
        raise ValueError("kappa needs at least 2 raters per item")
    for i, row in enumerate(ratings):
        if sum(row) != n_raters:
            raise ValueError(
                f"item {i} has {sum(row)} ratings but item 0 has {n_raters}; "
                "Fleiss' kappa requires the same number of raters for every item"
            )

    n_items = len(ratings)
    n_cats = len(ratings[0])

    # P_i: proportion of rater pairs on item i that agree.
    agreements = []
    for row in ratings:
        total = sum(count * (count - 1) for count in row)
        agreements.append(total / (n_raters * (n_raters - 1)))
    p_bar = sum(agreements) / n_items

    # p_j: overall proportion of ratings assigned to category j.
    category_totals = [
        sum(row[j] for row in ratings) / (n_items * n_raters) for j in range(n_cats)
    ]
    p_expected = sum(p * p for p in category_totals)

    if math.isclose(p_expected, 1.0):
        # Every rater used one category for everything. Agreement is perfect
        # but kappa is undefined (0/0): chance already predicts total
        # agreement. Report 1.0 rather than dividing by zero, and let the
        # write-up note that kappa is uninformative here.
        return 1.0

    return (p_bar - p_expected) / (1.0 - p_expected)


def interpret_kappa(kappa: float) -> str:
    """Landis & Koch (1977) labels.

    Included for readability, and to be treated with suspicion: these bands are
    conventional, not principled, and with 3-5 reviewers the confidence
    interval around any kappa is wide enough to span several of them.
    """
    if kappa < 0.0:
        return "worse than chance"
    if kappa < 0.20:
        return "slight"
    if kappa < 0.40:
        return "fair"
    if kappa < 0.60:
        return "moderate"
    if kappa < 0.80:
        return "substantial"
    return "almost perfect"


def proportion(successes: int, total: int) -> float:
    return successes / total if total else 0.0


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion.

    Used instead of the normal approximation because it behaves sensibly at
    small n and near 0 or 1 -- both of which this study will hit. Reporting an
    accuracy of 6/7 without an interval would imply a precision the sample
    cannot support.
    """
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    low = (centre - spread) / denominator
    high = (centre + spread) / denominator
    # Clamp: floating-point error puts the bound a hair outside [0, 1] at the
    # extremes (0/5 gives -3e-17), and a negative lower bound on a proportion
    # is not a number worth printing in a report.
    return (max(0.0, low), min(1.0, high))


def build_rating_matrix(
    decisions_by_change: dict[str, list[str]],
    categories: Sequence[str] = ("approve", "reject"),
) -> tuple[list[list[int]], list[str]]:
    """Turn per-change decision lists into a Fleiss rating matrix.

    Changes not rated by every reviewer are excluded, and their ids returned,
    because Fleiss' kappa is undefined for uneven rater counts. Dropping them
    silently would overstate agreement, so the caller is told which went.
    """
    if not decisions_by_change:
        return [], []

    counts = {cid: len(v) for cid, v in decisions_by_change.items()}
    expected = max(counts.values())

    matrix: list[list[int]] = []
    excluded: list[str] = []
    for change_id in sorted(decisions_by_change):
        verdicts = decisions_by_change[change_id]
        if len(verdicts) != expected:
            excluded.append(change_id)
            continue
        matrix.append([sum(1 for v in verdicts if v == cat) for cat in categories])
    return matrix, excluded
