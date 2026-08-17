"""Instrument validation. Runs with no API key and no network.

The fixtures in tests/fixtures/expected.json are hand-computed counts written
before the checker was ever run against them. These tests validate the
instrument against known counts; they do not validate the instrument against
itself.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from checker.h3 import (FailingH3Provider, HallucinatingH3Provider,
                        MockH3Provider, score_h3)
from checker.document import Document
from checker.score import blind_batch, content_hash, load_rubric, score_document

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED = json.loads((FIXTURES / "expected.json").read_text(encoding="utf-8"))
RUBRIC = load_rubric("meridian")
ALL_RULE_IDS = [r["id"] for r in RUBRIC["rules"]]

FIXTURE_NAMES = [k for k in EXPECTED if not k.startswith("_")]


def _score(name: str):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return score_document(text, RUBRIC, h3_provider=MockH3Provider())


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_fixture_full_vector(name):
    """Every fixture asserts all 14 rules, so detector cross-talk is caught."""
    expected = EXPECTED[name]["vector"]
    score = _score(name)
    actual = {rid: [score.rules[rid].count_raw, score.rules[rid].count_capped]
              for rid in ALL_RULE_IDS}
    wanted = {rid: expected.get(rid, [0, 0]) for rid in ALL_RULE_IDS}
    assert actual == wanted, (
        f"\n{name}\n"
        + "\n".join(f"  {rid}: expected {wanted[rid]} got {actual[rid]}"
                    for rid in ALL_RULE_IDS if wanted[rid] != actual[rid])
        + "\n  spans: "
        + json.dumps({rid: score.rules[rid].spans for rid in ALL_RULE_IDS
                      if wanted[rid] != actual[rid]}, indent=2)
    )


def test_clean_document_scores_zero():
    """The single most important property: silence on compliant text."""
    score = _score("clean_document.md")
    assert score.total_raw == 0
    assert score.total_capped == 0


def test_documented_false_positives_are_guarded():
    score = _score("false_positive_guards.md")
    assert score.total_raw == 0, {rid: r.spans for rid, r in score.rules.items()
                                  if r.count_raw}


def test_cap_applies_and_raw_is_still_recorded():
    score = _score("dirty_document.md")
    totals = EXPECTED["dirty_document.md"]["totals"]
    assert score.rules["H10"].count_raw == 8
    assert score.rules["H10"].count_capped == 5
    assert score.deterministic_raw == totals["deterministic_raw"]
    assert score.deterministic_capped == totals["deterministic_capped"]
    assert score.deterministic_raw > score.deterministic_capped


def test_h5_span_reports_the_whole_number_not_just_the_last_digit():
    """Spans are quoted into correction messages, so a truncated span is a bug."""
    score = _score("h5_span.md")
    assert score.rules["H5"].spans == ["30%"]


def test_deterministic_detectors_are_deterministic():
    """Same input, same output, twenty times. No hidden state, no randomness."""
    text = (FIXTURES / "dirty_document.md").read_text(encoding="utf-8")
    first = score_document(text, RUBRIC, MockH3Provider()).as_dict()
    for _ in range(19):
        assert score_document(text, RUBRIC, MockH3Provider()).as_dict() == first


def test_h3_and_deterministic_totals_are_reported_separately():
    text = (FIXTURES / "h3_passive.md").read_text(encoding="utf-8")
    score = score_document(text, RUBRIC, MockH3Provider())
    assert score.llm_raw == 1
    assert score.deterministic_raw == 0
    assert score.total_raw == score.llm_raw + score.deterministic_raw


# --- H3 provider contract -------------------------------------------------

def test_h3_discards_hallucinated_clauses():
    """A clause not present verbatim in the source cannot inflate the count."""
    doc = Document.parse(
        (FIXTURES / "h3_passive.md").read_text(encoding="utf-8"))
    honest = score_h3(doc, MockH3Provider())
    lying = score_h3(doc, HallucinatingH3Provider())
    assert honest.count_raw == 1
    assert lying.count_raw == 1, "hallucinated clause was counted"
    assert all(c in doc.raw for c in lying.clauses)


def test_h3_degrades_gracefully_when_the_model_call_fails():
    doc = Document.parse(
        (FIXTURES / "h3_passive.md").read_text(encoding="utf-8"))
    provider = FailingH3Provider()
    result = score_h3(doc, provider)
    assert result.status == "checker_error"
    assert result.count_raw == 0
    assert provider.calls == 2, "prompt contract requires exactly one retry"


def test_h3_skipped_when_no_provider_is_configured():
    """The deterministic subset must score with no model available at all."""
    text = (FIXTURES / "dirty_document.md").read_text(encoding="utf-8")
    score = score_document(text, RUBRIC, h3_provider=None)
    assert score.rules["H3"].status == "skipped"
    assert score.deterministic_raw == 12


def test_h3_tolerates_fenced_json():
    class Fenced(MockH3Provider):
        def complete(self, document_text: str) -> str:
            return "```json\n" + super().complete(document_text) + "\n```"

    doc = Document.parse(
        (FIXTURES / "h3_passive.md").read_text(encoding="utf-8"))
    assert score_h3(doc, Fenced()).count_raw == 1


# --- blinding contract ----------------------------------------------------

def test_scorer_has_no_parameter_that_could_carry_the_arm():
    params = set(inspect.signature(score_document).parameters)
    assert params == {"text", "rubric", "h3_provider"}
    forbidden = {"arm", "run_id", "ordinal", "client", "client_id",
                 "memory", "document_index", "prior_score"}
    assert not (params & forbidden)


def test_blind_batch_strips_ids_and_reorders():
    docs = {f"armB_doc_{i:02d}": f"Document number {i} text.\n" for i in range(20)}
    blinded = blind_batch(docs, seed=7)
    assert len(blinded) == 20
    assert all(len(h) == 16 and h.isalnum() for h, _ in blinded)
    assert [t for _, t in blinded] != list(docs.values()), "order not shuffled"
    assert not any("armB" in h for h, _ in blinded)
    # Rejoin is possible only by content hash, after scoring.
    assert {h for h, _ in blinded} == {content_hash(t) for t in docs.values()}


def test_blind_batch_is_reproducible_for_a_given_seed():
    docs = {f"d{i}": f"Text {i}.\n" for i in range(10)}
    assert blind_batch(docs, seed=3) == blind_batch(docs, seed=3)


# --- rubric integrity -----------------------------------------------------

def test_every_rule_has_a_detector_and_a_cap():
    from checker.detectors import DETERMINISTIC_DETECTORS
    for rule in RUBRIC["rules"]:
        assert rule["cap"] == 5
        if rule["detector"] == "deterministic":
            assert rule["id"] in DETERMINISTIC_DETECTORS
        else:
            assert rule["checker_prompt_version"]
            assert (Path(__file__).parent.parent / rule["checker_prompt"]).exists()


def test_llm_rules_are_pinned_to_a_committed_prompt_version():
    from checker.h3 import PROMPT_VERSION
    llm_rules = [r for r in RUBRIC["rules"] if r["detector"] == "llm"]
    assert len(llm_rules) == 1
    assert llm_rules[0]["checker_prompt_version"] == PROMPT_VERSION
    assert llm_rules[0]["reported_separately"] is True


def test_opposed_client_rubrics_are_actually_opposed():
    """Every shared axis must be mutually exclusive, or the leak test is blind."""
    a, b = load_rubric("northwind"), load_rubric("ember")
    axes_a = {r["axis"] for r in a["rules"] if r.get("axis")}
    axes_b = {r["axis"] for r in b["rules"] if r.get("axis")}
    shared = axes_a & axes_b
    assert len(shared) == 11, f"expected 11 opposed axes, got {sorted(shared)}"
    for axis in shared:
        ra = next(r for r in a["rules"] if r.get("axis") == axis)
        rb = next(r for r in b["rules"] if r.get("axis") == axis)
        compliant_a = set(ra["examples"]["compliant"])
        compliant_b = set(rb["examples"]["compliant"])
        assert not (compliant_a & compliant_b), f"axis {axis} is not opposed"
        # Nothing compliant for one client may be compliant for the other.
        assert not (compliant_a & set(rb["examples"]["compliant"]))
        assert not (compliant_b & set(ra["examples"]["compliant"]))
