from app.workflow.accuracy import (
    check_cross_field_consistency,
    check_source_grounding,
    downgrade_confidence,
    validate_currency,
    validate_field_types,
    validate_iso_date,
)


# --- currency validation -----------------------------------------------------


def test_valid_currency_formats_pass():
    for v in ["$84,000.00", "84000", "84000.50", "-500", "$1,234,567"]:
        assert validate_currency(v).valid is True, v


def test_malformed_currency_fails():
    for v in ["eighty four thousand", "$84,000.00.00", "84k", "N/A"]:
        assert validate_currency(v).valid is False, v


def test_none_currency_is_valid_absence_not_invalid():
    assert validate_currency(None).valid is True


# --- date validation ----------------------------------------------------------


def test_valid_iso_dates_pass():
    assert validate_iso_date("effective_date", "2026-01-15").valid is True


def test_malformed_date_format_fails():
    result = validate_iso_date("effective_date", "01/15/2026")
    assert result.valid is False


def test_invalid_calendar_date_fails_even_with_correct_format():
    result = validate_iso_date("effective_date", "2026-02-30")
    assert result.valid is False
    assert "calendar date" in result.reasons[0]


def test_none_date_is_valid_absence():
    assert validate_iso_date("effective_date", None).valid is True


# --- cross-field consistency --------------------------------------------------


def test_expiration_after_effective_is_consistent():
    result = check_cross_field_consistency("2026-01-15", "2027-01-14")
    assert result.valid is True


def test_expiration_before_effective_is_flagged():
    result = check_cross_field_consistency("2027-01-14", "2026-01-15")
    assert result.valid is False
    assert "before" in result.reasons[0]


def test_missing_one_date_skips_consistency_check():
    assert check_cross_field_consistency("2026-01-15", None).valid is True
    assert check_cross_field_consistency(None, None).valid is True


def test_malformed_dates_dont_double_report_as_inconsistent():
    # already-invalid dates are a format problem, not also blamed for
    # a false consistency violation
    result = check_cross_field_consistency("not-a-date", "2026-01-15")
    assert result.valid is True  # consistency check itself doesn't fire


# --- source grounding ----------------------------------------------------------


def test_value_present_in_source_is_grounded():
    source = "This Services Agreement is between Acme Logistics Inc and the Company."
    assert check_source_grounding("Acme Logistics Inc", source) is True


def test_value_absent_from_source_is_not_grounded():
    source = "This Services Agreement is between Acme Logistics Inc and the Company."
    assert check_source_grounding("Globex Corporation", source) is False


def test_grounding_is_case_and_whitespace_insensitive():
    source = "Counterparty:   ACME   Logistics    Inc\n"
    assert check_source_grounding("acme logistics inc", source) is True


def test_none_value_is_trivially_grounded():
    assert check_source_grounding(None, "any source text") is True


# --- downgrade_confidence ------------------------------------------------------


def test_passing_all_checks_leaves_confidence_unchanged():
    conf, notes = downgrade_confidence("counterparty_name", 0.9, type_valid=True, grounded=True)
    assert conf == 0.9
    assert notes == []


def test_failing_type_check_caps_confidence_low():
    conf, notes = downgrade_confidence("contract_value", 0.95, type_valid=False, grounded=True)
    assert conf <= 0.3
    assert any("validation" in n for n in notes)


def test_failing_grounding_caps_confidence_low():
    conf, notes = downgrade_confidence("counterparty_name", 0.95, type_valid=True, grounded=False)
    assert conf <= 0.3
    assert any("hallucination" in n for n in notes)


def test_downgrade_never_raises_confidence():
    conf, _ = downgrade_confidence("field", 0.1, type_valid=True, grounded=True)
    assert conf == 0.1  # already low, passing checks doesn't boost it


def test_validate_field_types_bundles_all_four_fields():
    results = validate_field_types(
        counterparty_name="Acme",
        effective_date="2026-01-15",
        expiration_date="not-a-date",
        contract_value="84000",
    )
    assert results["counterparty_name"].valid is True
    assert results["effective_date"].valid is True
    assert results["expiration_date"].valid is False
    assert results["contract_value"].valid is True
