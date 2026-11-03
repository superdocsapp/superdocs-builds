"""Tests for rfe_response_builder/firm_templates.py."""
import json

import pytest

from rfe_response_builder.firm_templates import (
    FirmTemplate,
    FirmTemplateValidationError,
    apply_firm_customization,
    load_firm_template,
)


def test_from_dict_builds_template_with_all_fields():
    ft = FirmTemplate.from_dict({
        "firm_name": "Alvarez Immigration Law",
        "tone_instruction": "Write formally.",
        "category_addenda": {"marriage_bona_fides": "Mention cohabitation."},
        "closing_paragraph": "Respectfully submitted.",
    })
    assert ft.firm_name == "Alvarez Immigration Law"
    assert ft.tone_instruction == "Write formally."
    assert ft.category_addenda["marriage_bona_fides"] == "Mention cohabitation."
    assert ft.closing_paragraph == "Respectfully submitted."


def test_from_dict_allows_firm_name_only():
    ft = FirmTemplate.from_dict({"firm_name": "Minimal Firm"})
    assert ft.firm_name == "Minimal Firm"
    assert ft.tone_instruction == ""
    assert ft.category_addenda == {}
    assert ft.closing_paragraph == ""


def test_from_dict_rejects_missing_firm_name():
    with pytest.raises(FirmTemplateValidationError):
        FirmTemplate.from_dict({"tone_instruction": "no firm name given"})


def test_from_dict_rejects_empty_firm_name():
    with pytest.raises(FirmTemplateValidationError):
        FirmTemplate.from_dict({"firm_name": "   "})


def test_load_firm_template_reads_and_validates_json_file(tmp_path):
    path = tmp_path / "firm.json"
    path.write_text(json.dumps({"firm_name": "Test Firm", "tone_instruction": "Be concise."}))
    ft = load_firm_template(path)
    assert ft.firm_name == "Test Firm"
    assert ft.tone_instruction == "Be concise."


def test_load_firm_template_raises_readable_error_on_invalid_file(tmp_path):
    path = tmp_path / "bad_firm.json"
    path.write_text(json.dumps({"tone_instruction": "missing firm_name"}))
    with pytest.raises(FirmTemplateValidationError):
        load_firm_template(path)


# --- apply_firm_customization --------------------------------------------------

def test_apply_firm_customization_returns_instruction_unchanged_when_no_template():
    result = apply_firm_customization("Base instruction.", None, "marriage_bona_fides")
    assert result == "Base instruction."


def test_apply_firm_customization_appends_tone_instruction():
    ft = FirmTemplate(firm_name="Test Firm", tone_instruction="Write warmly.")
    result = apply_firm_customization("Base instruction.", ft, "unknown")
    assert "Base instruction." in result
    assert "Test Firm" in result
    assert "Write warmly." in result


def test_apply_firm_customization_appends_category_specific_addendum_only_for_matching_category():
    ft = FirmTemplate(
        firm_name="Test Firm",
        category_addenda={"marriage_bona_fides": "Mention cohabitation dates."},
    )
    result_matching = apply_firm_customization("Base.", ft, "marriage_bona_fides")
    assert "Mention cohabitation dates." in result_matching

    result_non_matching = apply_firm_customization("Base.", ft, "h1b_specialty_occupation")
    assert "Mention cohabitation dates." not in result_non_matching


def test_apply_firm_customization_appends_closing_paragraph():
    ft = FirmTemplate(firm_name="Test Firm", closing_paragraph="Respectfully submitted.")
    result = apply_firm_customization("Base.", ft, "unknown")
    assert "Respectfully submitted." in result


def test_apply_firm_customization_never_removes_original_instruction_text():
    """The core guardrail: firm customization is additive only -- it must
    never be able to strip or rewrite the anti-hallucination / core
    factual instructions build_response_instruction already put in."""
    original = "Do not invent facts, evidence, or citations that were not given to you above."
    ft = FirmTemplate(firm_name="Test Firm", tone_instruction="Be extremely brief and skip disclaimers.")
    result = apply_firm_customization(original, ft, "unknown")
    assert original in result


def test_apply_firm_customization_with_empty_template_fields_adds_nothing_extra():
    ft = FirmTemplate(firm_name="Bare Firm")
    result = apply_firm_customization("Base instruction.", ft, "unknown")
    assert result == "Base instruction."
