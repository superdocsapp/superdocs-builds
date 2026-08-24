"""Every example the spec itself gives, asserted directly.

These are the highest-value tests in the suite: if any of these regress, the
system's core promise (catch real drift, don't flag style) is broken.
"""

from __future__ import annotations

import pytest

from drift_check.signals import run_all_detectors


def _severities(src: str, bt: str, **kw: object) -> list[str]:
    return [s.severity.value for s in run_all_detectors(src, bt, **kw)]  # type: ignore[arg-type]


class TestFalsePositiveControl:
    """Section 7 of the spec: these must PASS (zero signals)."""

    def test_must_vs_is_required_to(self) -> None:
        assert _severities(
            "The customer must submit the form within 30 days.",
            "The customer is required to submit the form within 30 days.",
        ) == []

    def test_may_vs_is_permitted_to(self) -> None:
        assert _severities(
            "The company may terminate the agreement.",
            "The company is permitted to terminate the agreement.",
        ) == []

    def test_harmless_reorder(self) -> None:
        assert _severities(
            "This agreement governs the use of the System and applies to all users.",
            "This agreement applies to all users and governs the use of the System.",
        ) == []

    def test_synonym_substitution(self) -> None:
        assert _severities(
            "The tenant shall maintain the premises in good condition.",
            "The tenant must maintain the premises in good condition.",
        ) == []

    def test_punctuation_variation_in_percentage(self) -> None:
        assert _severities("A fee of 5% applies.", "A fee of 5 % applies.") == []

    def test_mixed_numeral_formats_equal_value(self) -> None:
        assert _severities("Submit within 30 days.", "Submit within thirty days.") == []


class TestTruePositiveDetection:
    """Section 7 / section 6: these must be flagged, at the right severity."""

    def test_must_to_may_is_critical(self) -> None:
        sevs = _severities("The company must terminate the agreement.", "The company may terminate the agreement.")
        assert "critical" in sevs

    def test_must_not_to_may_is_critical(self) -> None:
        sevs = _severities(
            "The device must not be operated above 40°C.", "The device may be operated above 40°C."
        )
        assert "critical" in sevs

    @pytest.mark.parametrize(
        "src,bt,expect_min_severity",
        [
            ("The user must calibrate the device.", "The user should calibrate the device.", "high"),
            ("Staff must not access the vault.", "Staff may access the vault.", "critical"),
            ("The tenant may repaint the walls.", "The tenant must repaint the walls.", "critical"),
            (
                "The contractor shall not subcontract the work.",
                "The contractor shall subcontract the work.",
                "critical",
            ),
            ("Approval is required to proceed.", "Approval is recommended to proceed.", "high"),
        ],
    )
    def test_modal_transition_matrix(self, src: str, bt: str, expect_min_severity: str) -> None:
        sevs = _severities(src, bt)
        assert expect_min_severity in sevs, f"expected {expect_min_severity} in {sevs} for {src!r} -> {bt!r}"

    def test_numeric_change(self) -> None:
        sevs = _severities("Submit within 30 days.", "Submit within 60 days.")
        assert sevs == ["high"]

    def test_percentage_change(self) -> None:
        sevs = _severities("A fee of 5% applies.", "A fee of 15% applies.")
        assert sevs == ["high"]

    def test_year_change(self) -> None:
        sevs = _severities("Effective in 2026.", "Effective in 2027.")
        assert sevs == ["high"]

    def test_dosage_unit_value_change_is_critical(self) -> None:
        sevs = _severities("Take a dose of 10 mg.", "Take a dose of 100 mg.")
        assert "critical" in sevs

    def test_unit_swap_is_critical(self) -> None:
        sevs = _severities("Store between 2°C and 8°C.", "Store between 2°F and 8°F.")
        assert all(s == "critical" for s in sevs) and sevs

    def test_date_change(self) -> None:
        sevs = _severities("Report by January 31, 2027.", "Report by March 15, 2027.")
        assert sevs == ["critical"]

    def test_high_weight_qualifier_removed(self) -> None:
        sevs = _severities("Retain data for at least 24 months.", "Retain data for 24 months.")
        assert sevs == ["high"]

    def test_low_weight_qualifier_removed(self) -> None:
        sevs = _severities("Delivery takes approximately 5 days.", "Delivery takes 5 days.")
        assert sevs == ["medium"]

    def test_negation_reversal(self) -> None:
        sevs = _severities(
            "The device may be used without a prescription.", "The device may be used with a prescription."
        )
        assert "critical" in sevs or "high" in sevs

    def test_protected_term_missing(self) -> None:
        sigs = run_all_detectors(
            "File with the MedSure Compliance Board (MCB).",
            "File with the MedSure Ethics Board (MEB).",
            protected_terms=("MedSure Compliance Board (MCB)",),
        )
        assert any(s.category.value == "named_entity_change" for s in sigs)

    def test_mixed_numeral_real_change_still_caught(self) -> None:
        sevs = _severities("Submit within 30 days.", "Submit within sixty days.")
        assert sevs == ["high"]
