"""Northwind/Ember detector validation.

These detectors were written under the time pressure of the n=20 run rather
than with the same fixture-first, mutation-tested rigor the Meridian rubric
got (hand-computed expected.json, then a mutation pass). This is the fast,
honest substitute: every rule's OWN embedded compliant/violation examples in
rubrics/northwind.json and rubrics/ember.json are run through its detector.
Not as rigorous as the Meridian suite — no mutation testing, no adversarial
false-positive fixtures beyond what each rule's `examples` block already
states — but it is real validation against committed data, not zero
validation, and it runs before any of these detectors score a live document.
"""

from __future__ import annotations

import pytest

from checker.score import load_rubric, score_document
from checker.h3 import MockH3Provider

NORTHWIND = load_rubric("northwind")
EMBER = load_rubric("ember")


def _cases(rubric):
    for rule in rubric["rules"]:
        for kind in ("compliant", "violation"):
            for example in rule.get("examples", {}).get(kind, []):
                yield rubric["id"], rule["id"], kind, example


ALL_CASES = list(_cases(NORTHWIND)) + list(_cases(EMBER))


@pytest.mark.parametrize("rubric_id,rule_id,kind,example", ALL_CASES,
                        ids=[f"{r}_{i}_{k}" for r, i, k, _ in ALL_CASES])
def test_rule_scores_its_own_example_correctly(rubric_id, rule_id, kind,
                                               example):
    rubric = NORTHWIND if rubric_id == "northwind" else EMBER
    text = f"# Heading\n\n{example}\n" if not example.startswith(("#", "-", "*")) \
        else f"{example}\n"
    score = score_document(text, rubric, MockH3Provider())
    count = score.rules[rule_id].count_raw
    if kind == "compliant":
        assert count == 0, f"{rule_id} false-positived on its own compliant example: {example!r}"
    else:
        assert count >= 1, f"{rule_id} missed its own violation example: {example!r}"


def test_every_rule_has_at_least_one_example_of_each_kind():
    for rubric in (NORTHWIND, EMBER):
        for rule in rubric["rules"]:
            ex = rule.get("examples", {})
            assert ex.get("compliant"), f"{rule['id']} has no compliant example"
            assert ex.get("violation"), f"{rule['id']} has no violation example"


def test_client_rubrics_have_no_llm_rules():
    """Confirms the leak test needs no model call at all for scoring."""
    for rubric in (NORTHWIND, EMBER):
        assert all(r["detector"] == "deterministic" for r in rubric["rules"])


def test_score_document_never_raises_no_detector_for_a_client_rule():
    for rubric in (NORTHWIND, EMBER):
        text = "# A heading\n\nSome plain prose.\n"
        score = score_document(text, rubric, MockH3Provider())
        statuses = {rid: r.status for rid, r in score.rules.items()}
        assert all(s != "no_detector" for s in statuses.values()), statuses
