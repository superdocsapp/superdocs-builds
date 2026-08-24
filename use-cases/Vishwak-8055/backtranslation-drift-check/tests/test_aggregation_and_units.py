"""Finding aggregation and unit-conversion policy.

Added during pre-submission audit: two corroborating low-level signals about
one underlying problem must surface as one finding with multiple evidence
items (not inflate the finding count), and a unit-system change must be
checked against an explicit conversion policy rather than compared as raw
strings — see DECISIONS.md #10, #11 and LIMITATIONS.md #12.
"""

from __future__ import annotations

from drift_check.drift_engine import analyze_section_pair
from drift_check.models import BackTranslationResult, Section, SemanticAssessment
from drift_check.signals import run_all_detectors


def _pair_findings(source_text: str, bt_text: str, protected_terms: tuple[str, ...] = ()):
    source = Section(id="S1-a", index=1, heading="A", text=source_text, content_hash="x")
    target = Section(
        id="S1-a", index=1, heading="A", text="(translation not inspected by these tests)", content_hash="y"
    )
    bt = BackTranslationResult(
        target_section_id=target.id, text=bt_text, provider="fixture", model="fixture-v1", latency_ms=0.0,
        semantic_assessment=SemanticAssessment(has_drift=False, category=None, rationale="", confidence=0.9),
    )
    signals = run_all_detectors(source_text, bt_text, protected_terms=protected_terms)
    return analyze_section_pair(
        run_id="r1", source_document_id="d1", source_section=source, target_section=target, bt=bt,
        deterministic_signals=signals, alignment_review_required=False,
    )


class TestFindingAggregation:
    def test_two_unit_changes_in_one_section_become_one_finding(self) -> None:
        findings = _pair_findings("Store between 2°C and 8°C.", "Store between 2°F and 8°F.")
        unit_findings = [f for f in findings if f.category.value == "unit_change"]
        assert len(unit_findings) == 1
        assert len(unit_findings[0].evidence) == 2
        assert unit_findings[0].severity.value == "critical"

    def test_protected_term_and_heuristic_entity_match_become_one_finding(self) -> None:
        findings = _pair_findings(
            "File with the MedSure Compliance Board (MCB).",
            "File with the MedSure Ethics Board (MEB).",
            protected_terms=("MedSure Compliance Board (MCB)",),
        )
        entity_findings = [f for f in findings if f.category.value == "named_entity_change"]
        assert len(entity_findings) == 1
        assert len(entity_findings[0].evidence) >= 2

    def test_different_categories_stay_as_separate_findings(self) -> None:
        # A modal change and a qualifier change are two genuinely different
        # problems and must not be merged just because they're in one section.
        findings = _pair_findings(
            "The device must never be shared, under any circumstances, only by staff.",
            "The device may be shared, as long as approved, by staff.",
        )
        categories = {f.category.value for f in findings}
        assert "modal_obligation_change" in categories
        assert "qualifier_change" in categories
        assert len([f for f in findings if f.category.value == "modal_obligation_change"]) == 1
        assert len([f for f in findings if f.category.value == "qualifier_change"]) == 1

    def test_single_signal_finding_keeps_original_wording_unchanged(self) -> None:
        # Aggregation must not alter behavior for the (common) single-signal case.
        findings = _pair_findings("Submit within 30 days.", "Submit within 60 days.")
        assert len(findings) == 1
        assert findings[0].difference == "Value changed: '30 days' → '60 days'"

    def test_evidence_preserves_full_detail_even_when_summarized(self) -> None:
        findings = _pair_findings("Store between 2°C and 8°C.", "Store between 2°F and 8°F.")
        finding = [f for f in findings if f.category.value == "unit_change"][0]
        detail_texts = [e.description for e in finding.evidence]
        assert any("2°C" in d and "2°F" in d for d in detail_texts)
        assert any("8°C" in d and "8°F" in d for d in detail_texts)

    def test_aggregated_correction_target_is_still_translation_only(self) -> None:
        findings = _pair_findings("Store between 2°C and 8°C.", "Store between 2°F and 8°F.")
        finding = [f for f in findings if f.category.value == "unit_change"][0]
        assert finding.proposed_correction is not None
        assert finding.proposed_correction.correction_target == "translation"
        # A unit/value drift is never auto-rewritten (spec section 5.C) —
        # confirm no literal replacement was silently applied.
        assert finding.proposed_correction.suggested_text is None


class TestUnitConversionPolicy:
    def test_same_unit_same_value_passes(self) -> None:
        assert run_all_detectors("Store at 2°C.", "Store at 2°C.") == []

    def test_same_unit_changed_value_is_numeric_not_unit_change(self) -> None:
        sigs = run_all_detectors("Store at 2°C.", "Store at 8°C.")
        assert len(sigs) == 1
        assert sigs[0].category.value == "numeric_change"

    def test_legitimate_conversion_passes(self) -> None:
        assert run_all_detectors("Store at 2°C.", "Store at 35.6°F.") == []
        assert run_all_detectors("Weight is 2 kg.", "Weight is 2000 g.") == []
        assert run_all_detectors("Distance is 10 km.", "Distance is 6.2 miles.") == []

    def test_legitimate_conversion_tolerates_reasonable_rounding(self) -> None:
        assert run_all_detectors("Store at 2°C.", "Store at 36°F.") == []

    def test_invalid_conversion_is_flagged_critical(self) -> None:
        sigs = run_all_detectors("Store at 2°C.", "Store at 90°F.")
        assert len(sigs) == 1
        assert sigs[0].severity.value == "critical"
        assert "wrong" in sigs[0].difference.lower()

    def test_flat_unit_swap_with_unchanged_number_is_invalid_conversion(self) -> None:
        # The exact dangerous bug the flagship demo seeds: unit swapped, value
        # left untouched, which is almost never a coincidentally-correct conversion.
        sigs = run_all_detectors("Store at 2°C.", "Store at 2°F.")
        assert len(sigs) == 1
        assert sigs[0].severity.value == "critical"

    def test_unsupported_conversion_pair_is_flagged_not_guessed(self) -> None:
        sigs = run_all_detectors("Weight is 5 kg.", "Weight is 11 miles.")
        assert len(sigs) == 1
        assert "no configured conversion policy" in sigs[0].difference
        assert sigs[0].literal_replacement is None

    def test_missing_unit_on_one_side_does_not_crash(self) -> None:
        sigs = run_all_detectors("Store at 2°C.", "Store at a cool temperature.")
        # No paired unit_quantity token on the translation side — should not
        # raise, and should not silently invent a comparison.
        assert isinstance(sigs, list)

    def test_multiple_values_in_one_section_each_checked_independently(self) -> None:
        sigs = run_all_detectors(
            "Range is 2°C to 8°C.",
            "Range is 35.6°F to 8°F.",  # first is a correct conversion, second is not
        )
        assert len(sigs) == 1
        assert "8" in sigs[0].difference

    def test_unit_never_auto_rewritten(self) -> None:
        sigs = run_all_detectors("Store at 2°C.", "Store at 90°F.")
        assert all(s.literal_replacement is None for s in sigs)
