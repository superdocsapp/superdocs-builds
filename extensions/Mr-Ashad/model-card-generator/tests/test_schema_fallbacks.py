"""Tests for Schema Validation and Strict 'Not provided' Fallback Handling."""

import pytest
from src.normalizer import ManifestNormalizer, FALLBACK_VALUE, STANDARD_FIELDS


def test_empty_manifest_all_fields_fallback():
    """Verify that an empty manifest assigns 'Not provided' to all standard fields."""
    normalizer = ManifestNormalizer()
    empty_manifest = {}
    
    normalized = normalizer.normalize(empty_manifest)

    for field in STANDARD_FIELDS:
        assert field in normalized, f"Missing standard field: {field}"
        assert normalized[field] == FALLBACK_VALUE, (
            f"Field '{field}' should be '{FALLBACK_VALUE}', got '{normalized[field]}'"
        )


def test_missing_or_blank_values_become_fallback():
    """Verify that None, empty string, whitespace, empty list, and empty dict all resolve to 'Not provided'."""
    normalizer = ManifestNormalizer()
    sparse_manifest = {
        "model_name": "TestModel-7B",
        "version": "",                    # empty string
        "release_date": "   ",             # whitespace only
        "intended_purpose": None,          # None
        "limitations": [],                 # empty list
        "out_of_scope_uses": {},           # empty dict
        "maintenance_contact": None,
        "training_data_summary": "",
    }

    normalized = normalizer.normalize(sparse_manifest)

    assert normalized["model_name"] == "TestModel-7B"
    assert normalized["version"] == FALLBACK_VALUE
    assert normalized["release_date"] == FALLBACK_VALUE
    assert normalized["intended_purpose"] == FALLBACK_VALUE
    assert normalized["limitations"] == FALLBACK_VALUE
    assert normalized["out_of_scope_uses"] == FALLBACK_VALUE
    assert normalized["maintenance_contact"] == FALLBACK_VALUE
    assert normalized["training_data_summary"] == FALLBACK_VALUE


def test_nested_dict_partial_empty_fallbacks():
    """Verify that nested dictionaries have empty sub-properties converted to 'Not provided'."""
    normalizer = ManifestNormalizer()
    manifest_with_nested = {
        "model_name": "TestModel-7B",
        "maintenance_contact": {
            "team": "Core AI Team",
            "email": "",                    # empty subfield
            "security_reports": None        # None subfield
        }
    }

    normalized = normalizer.normalize(manifest_with_nested)
    contact = normalized["maintenance_contact"]

    assert isinstance(contact, dict)
    assert contact["team"] == "Core AI Team"
    assert contact["email"] == FALLBACK_VALUE
    assert contact["security_reports"] == FALLBACK_VALUE


def test_alias_resolution_preserves_provided_data():
    """Verify that alias fields (e.g. intended_use, contact, dataset_summary) are correctly mapped."""
    normalizer = ManifestNormalizer()
    manifest_with_aliases = {
        "model_name": "AliasModel-13B",
        "intended_use": ["Feature Extraction", "Summarization"],
        "contact": "support@example.com",
        "training_data": "500B tokens of English web text",
        "safety_and_alignment": ["RLHF applied"],
    }

    normalized = normalizer.normalize(manifest_with_aliases)

    assert normalized["intended_purpose"] == ["Feature Extraction", "Summarization"]
    assert normalized["maintenance_contact"] == "support@example.com"
    assert normalized["training_data_summary"] == "500B tokens of English web text"
    assert normalized["ethical_considerations"] == ["RLHF applied"]


def test_no_hallucination_guarantee():
    """Ensure that completely unmentioned optional fields are NEVER given synthetic defaults."""
    normalizer = ManifestNormalizer()
    minimal_manifest = {
        "model_name": "MinimalModel"
    }

    normalized = normalizer.normalize(minimal_manifest)

    # Specific check: never guess parameters, license, or training data
    assert normalized["model_architecture"] == FALLBACK_VALUE
    assert normalized["license"] == FALLBACK_VALUE
    assert normalized["training_data_summary"] == FALLBACK_VALUE
    assert normalized["hardware_and_compute"] == FALLBACK_VALUE


def test_format_markdown_field_helper():
    """Test the formatting helper for converting normalized values into Markdown."""
    normalizer = ManifestNormalizer()

    # Fallback string
    assert normalizer.format_markdown_field(FALLBACK_VALUE) == FALLBACK_VALUE
    assert normalizer.format_markdown_field(None) == FALLBACK_VALUE
    assert normalizer.format_markdown_field("") == FALLBACK_VALUE

    # List formatting
    list_val = ["Task A", "Task B"]
    formatted_list = normalizer.format_markdown_field(list_val)
    assert "- Task A\n- Task B" == formatted_list

    # Dict formatting
    dict_val = {"team": "Core AI", "email": "ai@example.com"}
    formatted_dict = normalizer.format_markdown_field(dict_val)
    assert "**Team**: Core AI" in formatted_dict
    assert "**Email**: ai@example.com" in formatted_dict
