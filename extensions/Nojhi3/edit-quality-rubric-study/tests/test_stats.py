"""Statistics tests: Cohen's kappa (unweighted + linear-weighted), percent
agreement, confusion matrices, Landis-Koch bands, bootstrap CIs, and analyze()
on synthetic sheets. Expected values are hand-derived in the comments."""

import math

import pytest

from app.analysis import analyze, band, bootstrap_ci, cohens_kappa, confusion_matrix, percent_agreement


class TestCohensKappa:
    def test_perfect_agreement_is_1(self):
        pairs = [(1, 1), (1, 1), (2, 2), (3, 3), (4, 4)]
        assert cohens_kappa(pairs) == 1.0

    def test_chance_agreement_is_0(self):
        # po = 0.5; rows {1:2,2:2}, cols {1:2,2:2} -> pe = 0.5 -> kappa 0
        pairs = [(1, 1), (2, 1), (1, 2), (2, 2)]
        assert cohens_kappa(pairs) == 0.0

    def test_unbalanced_negative_kappa(self):
        # rows {1:3,2:1}, cols {1:3,2:1}: po = 2/4 = 0.5,
        # pe = (3/4)^2 + (1/4)^2 = 0.625 -> kappa = (0.5-0.625)/0.375 = -1/3
        pairs = [(1, 1), (1, 1), (1, 2), (2, 1)]
        assert cohens_kappa(pairs) == pytest.approx(-1.0 / 3.0, abs=1e-12)

    def test_single_category_returns_1(self):
        assert cohens_kappa([(4, 4), (4, 4)]) == 1.0

    def test_empty_pairs_raises(self):
        with pytest.raises(ValueError):
            cohens_kappa([])

    def test_mixed_valid_and_out_of_scale_inputs_stay_in_bounds(self):
        # out-of-scale scores are contractually excluded upstream (valid_score);
        # the function must still return a finite kappa in [-1, 1]
        kappa = cohens_kappa([(2, 2), (3, 3), (1, 4)])
        assert -1.0 <= kappa <= 1.0

    def test_hand_derived_weighted_kappa(self):
        # pairs [(1,1),(2,2),(3,3),(4,2)], weights w = 1 - |a-b|/3:
        # rows/cols: {1:1,2:1,3:1,4:1} x {1:1,2:2,3:1,4:0}
        # unweighted: po = 3/4, pe = (1+2+1+0)/16 = 1/4 -> kappa = 2/3
        # weighted:   po = (1+1+1+1/3)/4 = 5/6; pe = (8/3+10/3+8/3+4/3)/16 = 5/8
        #            -> kappa_w = (5/6-5/8)/(1-5/8) = 5/9
        pairs = [(1, 1), (2, 2), (3, 3), (4, 2)]
        assert cohens_kappa(pairs) == pytest.approx(2.0 / 3.0, abs=1e-12)
        assert cohens_kappa(pairs, weighted=True) == pytest.approx(5.0 / 9.0, abs=1e-12)

    def test_weighted_kappa_disagreement_counts_less(self):
        # one step off (diff 1) vs two steps off (diff 2) on identical marginals
        near = [(1, 2), (2, 3), (3, 4), (4, 4)]
        far = [(1, 3), (2, 4), (3, 4), (4, 4)]
        assert cohens_kappa(near, weighted=True) > cohens_kappa(far, weighted=True)
        assert cohens_kappa(near) == cohens_kappa(far)  # unweighted identical

    def test_extreme_disagreement_hand_derived(self):
        # pairs [(1,4),(2,2),(3,3)], w = 1 - |a-b|/3:
        # rows {1:1,2:1,3:1}, cols {2:1,3:1,4:1}
        # unweighted: po = 2/3, pe = (0+1+1+0)/9 = 2/9 -> kappa = 4/7
        # weighted:   po = (0+1+1)/3 = 2/3; pe = (1+2+7/3)/9 = 16/27
        #            -> kappa_w = (2/3-16/27)/(1-16/27) = 2/11
        pairs = [(1, 4), (2, 2), (3, 3)]
        assert cohens_kappa(pairs) == pytest.approx(4.0 / 7.0, abs=1e-12)
        assert cohens_kappa(pairs, weighted=True) == pytest.approx(2.0 / 11.0, abs=1e-12)


class TestPercentAgreement:
    def test_exact(self):
        assert percent_agreement([(1, 1), (2, 2), (3, 3), (4, 2)]) == 0.75

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            percent_agreement([])


class TestConfusionMatrix:
    def test_structure_and_counts(self):
        pairs = [(1, 1), (1, 2), (3, 4), (4, 2)]
        cm = confusion_matrix(pairs)
        assert cm[1][1] == 1 and cm[1][2] == 1
        assert cm[3][4] == 1 and cm[4][2] == 1
        assert cm[2][1] == 0
        assert sum(cm[a][b] for a in range(1, 5) for b in range(1, 5)) == 4

    def test_diagonal_is_exact_agreement(self):
        cm = confusion_matrix([(2, 2), (3, 4)])
        assert cm[2][2] == 1 and cm[3][4] == 1


class TestBand:
    @pytest.mark.parametrize("value,label", [
        (0.81, "almost perfect"), (0.61, "substantial"), (0.607, "moderate"),
        (0.41, "moderate"), (0.409, "fair"), (0.21, "fair"), (0.209, "slight"),
        (0.0, "slight"), (-0.01, "poor"), (-2.0, "poor"),
    ])
    def test_edges(self, value, label):
        assert band(value) == label


class TestBootstrapCI:
    def test_deterministic_seed(self):
        pairs = [(1, 1), (1, 2), (2, 2), (3, 3), (4, 4), (2, 1)]
        a = bootstrap_ci(pairs, cohens_kappa, iterations=200, seed=7)
        b = bootstrap_ci(pairs, cohens_kappa, iterations=200, seed=7)
        assert a == b

    def test_bounds_sane(self):
        pairs = [(1, 1), (1, 2), (2, 2), (3, 3), (4, 4), (2, 1)]
        lo, hi = bootstrap_ci(pairs, cohens_kappa, iterations=500, seed=7)
        assert -1.0 <= lo <= hi <= 1.0

    def test_perfect_agreement_ci_collapses(self):
        pairs = [(1, 1), (2, 2), (3, 3), (4, 4)] * 5
        lo, hi = bootstrap_ci(pairs, cohens_kappa, iterations=200, seed=7)
        assert lo == 1.0 and hi == 1.0


class TestAnalyze:
    def _sheets(self):
        human = {}
        auto = {}
        for cid, h_scores in {
            "c1": {"faithfulness": 4, "fact_accuracy": 3, "content_preservation": 4,
                   "structural_integrity": 4, "formatting_fidelity": 4, "language_quality": 4},
            "c2": {"faithfulness": 2, "fact_accuracy": 1, "content_preservation": 4,
                   "structural_integrity": 2, "formatting_fidelity": 1, "language_quality": 4},
        }.items():
            human[cid] = {"scores": h_scores, "evidence": {d: f"h:{d}" for d in h_scores}}
            auto[cid] = {"scores": {d: s for d, s in h_scores.items()}, "evidence": {}}
        # c2: auto scores everything 2 steps off on faithfulness and fact_accuracy
        for d in ("faithfulness", "fact_accuracy"):
            auto["c2"]["scores"][d] = 4
        return human, auto

    def test_overall_matches_independent_computation(self):
        human, auto = self._sheets()
        res = analyze(human, auto, {c: {"difficulty": "easy", "instruction": ""} for c in ("c1", "c2")})
        all_pairs = []
        for cid in ("c1", "c2"):
            for d in human[cid]["scores"]:
                all_pairs.append((human[cid]["scores"][d], auto[cid]["scores"][d]))
        assert res["overall"]["n_cases"] == 2
        assert res["overall"]["n_judgments"] == 12
        # analyze() rounds to 3 decimals; compare with matching tolerance
        assert res["overall"]["percent_agreement"] == pytest.approx(
            round(percent_agreement(all_pairs), 3), abs=1e-12)
        assert res["overall"]["kappa"] == pytest.approx(round(cohens_kappa(all_pairs), 3), abs=1e-12)
        assert res["overall"]["kappa_linear_weighted"] == pytest.approx(
            round(cohens_kappa(all_pairs, weighted=True), 3), abs=1e-12)

    def test_per_dimension_values(self):
        human, auto = self._sheets()
        res = analyze(human, auto)
        f = res["dimensions"]["faithfulness"]
        assert f["n"] == 2
        # pairs: (4,4), (2,4) -> po = 0.5
        assert f["percent_agreement"] == pytest.approx(0.5)
        assert f["kappa"] == pytest.approx(cohens_kappa([(4, 4), (2, 4)]))
        assert f["confusion"][2][4] == 1
        assert f["human_mean"] == pytest.approx(3.0)
        assert f["auto_mean"] == pytest.approx(4.0)

    def test_disagreements_sorted_by_magnitude(self):
        human, auto = self._sheets()
        res = analyze(human, auto)
        diffs = [d["diff"] for d in res["disagreements"]]
        assert diffs == sorted(diffs, key=abs, reverse=True)
        assert any(d["case_id"] == "c2" and d["dimension"] == "faithfulness"
                   and d["diff"] == -2 for d in res["disagreements"])

    def test_distributions(self):
        human, auto = self._sheets()
        res = analyze(human, auto)
        # c1 human: five 4s; c2 human: two 4s -> 7
        assert res["distributions"]["human"]["4"] == 7
        # c1 auto: five 4s; c2 auto: faith/fact/content/lang 4s -> 9
        assert res["distributions"]["auto"]["4"] == 9

    def test_partial_overlap_only_uses_shared_cases(self):
        human, auto = self._sheets()
        auto.pop("c1")
        res = analyze(human, auto)
        assert res["case_ids"] == ["c2"]
        assert res["overall"]["n_cases"] == 1

    def test_kappa_ci_bounds(self):
        human, auto = self._sheets()
        res = analyze(human, auto)
        lo, hi = res["overall"]["kappa_ci95"]
        assert -1.0 <= lo <= hi <= 1.0
        assert math.isfinite(lo) and math.isfinite(hi)


class TestAnalyzeDegenerate:
    def test_single_shared_case_all_agree(self):
        sheets = {d: 4 for d in
                  ("faithfulness", "fact_accuracy", "content_preservation",
                   "structural_integrity", "formatting_fidelity", "language_quality")}
        human = {"c1": {"scores": dict(sheets)}}
        auto = {"c1": {"scores": dict(sheets)}}
        res = analyze(human, auto)
        assert res["overall"]["kappa"] == 1.0
        assert res["overall"]["percent_agreement"] == 1.0
        assert res["disagreements"] == []