"""The observational-language rail.

Two directions matter equally: the rail must catch certification language, and it must not
refuse the ordinary vocabulary of a real inspection report. A rail that fails the second test
gets switched off, which is the same as not having one.
"""

from __future__ import annotations

import pytest

from inspection_report.phrasing import rail

# Verbatim output from SuperDocs' AI on this build's first live drafting sample. It was asked
# only to draft a report with one finding per system — nothing adversarial. These are the
# sentences that made the rail non-negotiable, so they are the regression suite.
LIVE_AI_OUTPUT = [
    "GFCI outlet in the kitchen is not functioning correctly. Recommend replacement for safety.",
    "HVAC unit is older but operational; filter is excessively dirty.",
    "Minor settling crack observed in the basement foundation wall, typical for the home's age.",
]


class TestCatchesCertificationLanguage:
    @pytest.mark.parametrize("text", LIVE_AI_OUTPUT)
    def test_real_ai_output_is_refused(self, text: str) -> None:
        assert not rail.check(text).clean

    @pytest.mark.parametrize(
        "text,rule_id",
        [
            ("We certify the roof covering is sound.", "certification"),
            ("This inspection certifies the panel.", "certification"),
            ("The workmanship is guaranteed for five years.", "guarantee"),
            ("The seller warrants the water heater.", "guarantee"),
            ("The wiring is up to code.", "code_compliance"),
            ("Panel is code-compliant throughout.", "code_compliance"),
            ("The property passed inspection.", "pass_fail"),
            ("The foundation failed testing.", "pass_fail"),
            ("The building is structurally sound.", "condition_verdict"),
            ("The roof is in good condition.", "condition_verdict"),
            ("No defects were found anywhere.", "unscoped_negative"),
            ("The system is defect-free.", "absolute_negative"),
            ("The stair rail is safe to use.", "safety_assurance"),
            ("Recommend replacement for safety.", "safety_assurance"),
            ("The covering will last another fifteen years.", "lifespan_prediction"),
            ("Remaining useful life is about a decade.", "lifespan_prediction"),
            ("Repair costs about $400.", "cost_estimate"),
            ("This is nothing to worry about.", "reassurance"),
            ("Cracking is typical for the age of the home.", "reassurance"),
        ],
    )
    def test_each_rule_fires(self, text: str, rule_id: str) -> None:
        verdict = rail.check(text)
        assert not verdict.clean
        assert rule_id in {b.rule_id for b in verdict.breaches}

    def test_a_breach_explains_itself(self) -> None:
        """The reviewer is shown why, and what to write instead — not just a refusal."""
        breach = rail.check("We certify the roof is sound.").breaches[0]
        assert breach.why
        assert breach.suggest
        assert breach.matched.lower().startswith("certif")


class TestAllowsRealInspectionLanguage:
    @pytest.mark.parametrize(
        "text",
        [
            "Found displaced flashing at the north chimney. Recommend further evaluation.",
            "Observed staining on the ceiling below the bathroom. Recommend evaluation.",
            "The panel cover was not accessible at the time of inspection.",
            "Two receptacles showed an open ground when tested.",
            "Recommend prompt evaluation by a licensed electrician.",
            "Gutters were full of debris. Recommend maintenance.",
            "Safety glazing is present at the patio door.",
            "The pressure relief valve discharge terminates above grade.",
            "Could not be inspected: the crawlspace hatch was blocked by stored items.",
            # The English verb "warrant", which an inspection report uses constantly.
            "An observation that warrants evaluation and likely repair.",
            "The items that warrant the soonest attention come first.",
            "This finding warrants further review by a specialist.",
            # The report's own standing disclaimer must survive its own rail.
            "It is not a certification, warranty or guarantee of the condition of the property.",
        ],
    )
    def test_observational_prose_passes(self, text: str) -> None:
        verdict = rail.check(text)
        assert verdict.clean, verdict.summary()

    def test_empty_text_is_not_a_breach(self) -> None:
        assert rail.check("").clean
        assert rail.check("   ").clean


class TestScopedTerms:
    """Terms that are honest when tied to the moment of observation, and claims when not."""

    def test_unscoped_functional_claim_is_refused(self) -> None:
        assert not rail.check("The furnace is operational.").clean

    def test_scoped_functional_claim_is_allowed(self) -> None:
        v = rail.check("The furnace operated normally when tested.")
        assert v.clean, v.summary()

    def test_scoped_by_inspection_date_is_allowed(self) -> None:
        v = rail.check("The unit was functioning normally at the time of inspection.")
        assert v.clean, v.summary()

    def test_bare_negative_observation_is_refused(self) -> None:
        assert not rail.check("There are no leaks under the sink.").clean

    def test_scoped_negative_observation_is_allowed(self) -> None:
        v = rail.check("No leaks were observed under the sink.")
        assert v.clean, v.summary()

    def test_the_rails_own_suggested_wording_passes_its_own_rules(self) -> None:
        """A rule that forbids the sentence it recommends is a rule that gets ignored."""
        for r in rail.describe_rules():
            suggestion = r["suggest"].strip().strip('"')
            if suggestion.startswith(("Describe", "State", "Report", "Recommend", "Note")):
                continue  # an instruction to the writer, not example prose
            v = rail.check(suggestion)
            assert v.clean, f"rule {r['id']} suggests wording its own rail refuses: {v.summary()}"


class TestGate:
    """What the pipeline actually calls: decide which text may be used."""

    def test_a_clean_rewrite_is_taken(self) -> None:
        original = "S flashing gap ~2in @ chimney, staining below"
        proposed = (
            "Found a gap of roughly two inches in the flashing where the chimney meets the "
            "roof, with staining on the ceiling below. Recommend evaluation by a roofer."
        )
        used, verdict = rail.gate(original=original, proposed=proposed)
        assert verdict.clean
        assert used == proposed

    def test_a_certifying_rewrite_is_refused_and_the_inspector_keeps_the_page(self) -> None:
        original = "GFCI kitchen - no trip on test button"
        proposed = (
            "The kitchen GFCI is not functioning correctly. Recommend replacement for safety."
        )
        used, verdict = rail.gate(original=original, proposed=proposed)
        assert not verdict.clean
        assert used == original, "a refused rewrite must leave the inspector's own words in place"

    def test_the_rail_never_runs_on_the_inspectors_own_words(self) -> None:
        """gate() judges the proposal only. The inspector is the licensed professional."""
        original = "Roof is in good condition and up to code."  # would breach if checked
        proposed = "Found the roof covering intact, with no deficiencies observed."
        used, verdict = rail.gate(original=original, proposed=proposed)
        assert verdict.clean
        assert used == proposed


def test_every_rule_is_documented() -> None:
    """A rule the UI cannot explain is a rule a reviewer will not trust."""
    rules = rail.describe_rules()
    assert len(rules) >= 10
    for r in rules:
        assert r["why"], f"rule {r['id']} has no explanation"
        assert r["suggest"], f"rule {r['id']} suggests no alternative"


class TestComplianceIsCaughtInAnyWordOrder:
    """The rule matches the claim, not one arrangement of it.

    The first version listed noun forms in a single order — "code compliant", "meets code" —
    and let "the wiring is fully compliant with current code" through, which is the same
    claim with the words reversed. Compliance is an authority's determination however it is
    phrased.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "the wiring is fully compliant with current code",
            "the panel is code compliant",
            "brought up to code in 2011",
            "the installation complies with the standard",
            "the flue conforms to the manufacturer instructions",
            "not compliant with current requirements",
            "this meets the code",
        ],
    )
    def test_a_compliance_claim_is_refused(self, text: str) -> None:
        verdict = rail.check(text)
        assert not verdict.clean, text
        assert any(b.category == "code" for b in verdict.breaches), verdict.summary()

    @pytest.mark.parametrize(
        "text",
        [
            "safety glazing present at the tub surround",
            "no leaks were observed at the time of inspection",
            "warrants evaluation by a licensed electrician",
            "operated normally when tested at the time of inspection",
            "downpipe discharging at the foundation",
            "recommend review by the local authority having jurisdiction",
        ],
    )
    def test_real_inspection_vocabulary_still_passes(self, text: str) -> None:
        """Refusing valid work is a failure of equal weight to permitting a bad claim."""
        assert rail.check(text).clean, rail.check(text).summary()
