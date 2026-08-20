"""Inter-rater agreement statistics, pure Python (no scipy).

Cohen's kappa (unweighted and linear-weighted), percent agreement, confusion
matrices, percentile bootstrap CIs on item resampling, and the disagreement
case review. Small samples are reported with their wide CIs, not hidden.
"""

import random
from collections import defaultdict

from .rubric import DIMENSION_IDS, load_rubric

SCALE_MAX = 4
LANDIS_KOCH = [
    (0.81, "almost perfect"),
    (0.61, "substantial"),
    (0.41, "moderate"),
    (0.21, "fair"),
    (0.0, "slight"),
    (-1.0, "poor"),
]


def band(kappa: float) -> str:
    for lo, label in LANDIS_KOCH:
        if kappa >= lo:
            return label
    return "poor"


def _weights_matrix() -> dict:
    w = {}
    for i in range(1, SCALE_MAX + 1):
        for j in range(1, SCALE_MAX + 1):
            w[(i, j)] = 1.0 - abs(i - j) / (SCALE_MAX - 1)
    return w


def cohens_kappa(pairs: list[tuple[int, int]], weighted: bool = False) -> float:
    """pairs: list of (rater_a_score, rater_b_score). 1 category = undefined."""
    n = len(pairs)
    if n == 0:
        raise ValueError("no pairs")
    obs = defaultdict(int)
    for a, b in pairs:
        obs[(a, b)] += 1
    categories = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    if len(categories) < 2:
        return 1.0 if len(categories) == 1 and all(a == b for a, b in pairs) else 0.0
    rows = {c: sum(v for (a, b), v in obs.items() if a == c) for c in categories}
    cols = {c: sum(v for (a, b), v in obs.items() if b == c) for c in categories}

    w = _weights_matrix() if weighted else {(i, j): 1.0 if i == j else 0.0 for i in categories for j in categories}
    po = sum(obs[(a, b)] * w.get((a, b), 0.0) for a in categories for b in categories) / n
    pe = sum(rows[a] * cols[b] * w.get((a, b), 0.0) for a in categories for b in categories) / (n * n)
    if pe == 1.0:
        return 1.0
    if po == pe:
        return 0.0
    return (po - pe) / (1.0 - pe)


def percent_agreement(pairs: list[tuple[int, int]]) -> float:
    if not pairs:
        raise ValueError("no pairs")
    return sum(1 for a, b in pairs if a == b) / len(pairs)


def confusion_matrix(pairs: list[tuple[int, int]]) -> dict:
    matrix = {i: {j: 0 for j in range(1, SCALE_MAX + 1)} for i in range(1, SCALE_MAX + 1)}
    for a, b in pairs:
        matrix[a][b] += 1
    return matrix


def bootstrap_ci(pairs: list[tuple[int, int]], stat_fn, iterations: int = 2000, seed: int = 7) -> tuple[float, float]:
    """Percentile bootstrap 95% CI by resampling items (with replacement)."""
    rng = random.Random(seed)
    n = len(pairs)
    if n == 0:
        return (float("nan"), float("nan"))
    samples = []
    for _ in range(iterations):
        resample = [pairs[rng.randrange(n)] for _ in range(n)]
        try:
            samples.append(stat_fn(resample))
        except (ValueError, ZeroDivisionError):
            continue
    if not samples:
        return (float("nan"), float("nan"))
    samples.sort()
    lo = samples[int(0.025 * len(samples))]
    hi = samples[int(0.975 * len(samples))]
    return (lo, hi)


def analyze(human: dict, auto: dict, case_meta: dict = None, iterations: int = 2000) -> dict:
    """human/auto: {case_id: sheet}. Returns full analysis dict."""
    rubric = load_rubric()
    case_ids = sorted(set(human) & set(auto))
    per_dim = {d: {"pairs": [], "cases": []} for d in DIMENSION_IDS}
    for cid in case_ids:
        hs = human[cid]["scores"]
        a_s = auto[cid]["scores"]
        for d in DIMENSION_IDS:
            per_dim[d]["pairs"].append((hs[d], a_s[d]))
            per_dim[d]["cases"].append(cid)

    dims = {}
    for d in DIMENSION_IDS:
        pairs = per_dim[d]["pairs"]
        kappa = cohens_kappa(pairs, weighted=False)
        kappa_w = cohens_kappa(pairs, weighted=True)
        kappa_ci = bootstrap_ci(pairs, lambda p: cohens_kappa(p, weighted=False), iterations)
        kappa_w_ci = bootstrap_ci(pairs, lambda p: cohens_kappa(p, weighted=True), iterations)
        dims[d] = {
            "label": next(x["label"] for x in rubric["dimensions"] if x["id"] == d),
            "n": len(pairs),
            "percent_agreement": round(percent_agreement(pairs), 3),
            "kappa": round(kappa, 3),
            "kappa_ci95": [round(kappa_ci[0], 3), round(kappa_ci[1], 3)],
            "kappa_band": band(kappa),
            "kappa_linear_weighted": round(kappa_w, 3),
            "kappa_linear_weighted_ci95": [round(kappa_w_ci[0], 3), round(kappa_w_ci[1], 3)],
            "confusion": confusion_matrix(pairs),
            "human_mean": round(sum(p[0] for p in pairs) / len(pairs), 3),
            "auto_mean": round(sum(p[1] for p in pairs) / len(pairs), 3),
        }

    all_pairs = []
    for d in DIMENSION_IDS:
        all_pairs.extend(per_dim[d]["pairs"])
    overall = {
        "n_cases": len(case_ids),
        "n_judgments": len(all_pairs),
        "percent_agreement": round(percent_agreement(all_pairs), 3),
        "kappa": round(cohens_kappa(all_pairs, weighted=False), 3),
        "kappa_linear_weighted": round(cohens_kappa(all_pairs, weighted=True), 3),
        "kappa_ci95": [round(x, 3) for x in bootstrap_ci(all_pairs, lambda p: cohens_kappa(p, weighted=False), iterations)],
    }

    disagreements = []
    for cid in case_ids:
        for d in DIMENSION_IDS:
            diff = human[cid]["scores"][d] - auto[cid]["scores"][d]
            if abs(diff) >= 2:
                disagreements.append({
                    "case_id": cid,
                    "dimension": d,
                    "human": human[cid]["scores"][d],
                    "auto": auto[cid]["scores"][d],
                    "diff": diff,
                    "human_evidence": human[cid].get("evidence", {}).get(d, ""),
                    "auto_evidence": auto[cid].get("evidence", {}).get(d, ""),
                    "difficulty": (case_meta or {}).get(cid, {}).get("difficulty", "?"),
                    "instruction": (case_meta or {}).get(cid, {}).get("instruction", ""),
                })
    disagreements.sort(key=lambda x: -abs(x["diff"]))

    def _distribution(sheets: dict) -> dict:
        dist = {v: 0 for v in range(1, 5)}
        for cid in case_ids:
            for d in DIMENSION_IDS:
                dist[sheets[cid]["scores"][d]] += 1
        return {str(k): v for k, v in sorted(dist.items())}

    distributions = {
        "human": _distribution(human),
        "auto": _distribution(auto),
    }

    return {"dimensions": dims, "overall": overall, "disagreements": disagreements,
            "case_ids": case_ids, "distributions": distributions}