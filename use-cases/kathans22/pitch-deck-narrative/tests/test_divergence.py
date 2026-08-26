"""Hand-made divergence fixtures — no SuperDocs, no network."""

from __future__ import annotations

from generator.divergence import (
    VERTICAL_MEAN_MAX,
    VERTICAL_SECTION_MAX,
    evaluate_divergence,
    score_all,
    score_pair,
)


def test_identical_texts_score_maximum_overlap() -> None:
    text = (
        "ClarityDocs stages every finding for human approval before anything commits."
    )
    assert score_pair(text, text) == 1.0
    assert score_pair("", "") == 0.0


def test_template_and_swap_scores_high_and_is_caught() -> None:
    """Only the buyer noun changes — scorer must flag this as a swap failure."""
    legal = (
        "The legal team reviews every finding before it commits to the client pack."
    )
    compliance = (
        "The compliance team reviews every finding before it commits to the client pack."
    )
    overlap = score_pair(legal, compliance)
    assert overlap >= VERTICAL_SECTION_MAX, overlap
    assert overlap >= 0.7, overlap

    weights = {7: "vertical"}
    report = score_all(
        {
            "legal": {7: legal},
            "fintech": {7: compliance},
        },
        weights,
    )
    evaluation = evaluate_divergence(report, weights)
    assert evaluation["passed"] is False
    assert evaluation["mean_vertical_overlap"] >= VERTICAL_MEAN_MAX
    assert any("template-and-swap" in f or ">=" in f for f in evaluation["failures"])


def test_genuinely_distinct_text_scores_low() -> None:
    legal_pain = (
        "Clause libraries drift across matters; associates paste from the wrong prior "
        "without provenance and partners re-litigate the same family of redlines."
    )
    fintech_pain = (
        "Policy packs go stale after each product launch; examiner evidence for one "
        "control lives in three folders and is rebuilt from chat threads under pressure."
    )
    overlap = score_pair(legal_pain, fintech_pain)
    assert overlap < VERTICAL_MEAN_MAX, overlap
    assert overlap < 0.25, overlap

    weights = {2: "vertical"}
    report = score_all(
        {"legal": {2: legal_pain}, "fintech": {2: fintech_pain}},
        weights,
    )
    evaluation = evaluate_divergence(report, weights)
    assert evaluation["passed"] is True
    assert evaluation["mean_vertical_overlap"] < VERTICAL_MEAN_MAX


def test_aggregation_by_weight_on_synthetic_verticals() -> None:
    """Shared sections may overlap highly; vertical means stay separate and correct."""
    weights = {1: "shared", 2: "vertical", 7: "vertical"}
    narratives = {
        "legal": {
            1: "ClarityDocs helps teams export approved work as ordinary documents.",
            2: "Matter playbooks drift and conflict checks miss clause provenance.",
            7: "Precedents are our moat; keep matter walls closed to shared AI workspaces.",
        },
        "fintech": {
            1: "ClarityDocs helps teams export approved work as ordinary documents.",
            2: "BSA evidence packs lag product releases and SOC narratives contradict folders.",
            7: "Invented attestations poison examiner packs; humans must gate each finding.",
        },
        "healthcare": {
            1: "ClarityDocs helps teams export approved work as ordinary documents.",
            2: "Discharge packets diverge across sites and imply clinical guarantees nobody signed.",
            7: "Nothing that touches patient text ships without a named human gate.",
        },
    }
    report = score_all(narratives, weights)
    agg = report["aggregates"]

    assert agg["shared_cells"] == 3  # three pairs × one shared section
    assert agg["vertical_cells"] == 6  # three pairs × two vertical sections
    assert agg["mean_shared_overlap"] == 1.0
    assert agg["mean_vertical_overlap"] is not None
    assert agg["mean_vertical_overlap"] < VERTICAL_MEAN_MAX
    assert len(report["pairs"]) == 3
    assert len(report["per_pair_aggregates"]) == 3

    for pair_agg in report["per_pair_aggregates"]:
        assert pair_agg["mean_shared_overlap"] == 1.0
        assert pair_agg["mean_vertical_overlap"] < VERTICAL_MEAN_MAX

    evaluation = evaluate_divergence(report, weights)
    assert evaluation["passed"] is True
