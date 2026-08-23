"""
Tests for rfe_response_builder/schemas.py.

This module had ZERO dedicated tests before this file existed -- it was
only ever exercised indirectly through generate.py/app.py's loaders with
already-valid sample data, which never triggered validation failures at
all. That gap is exactly what let a real bug (jsonschema's `minLength`
does not reject whitespace-only strings -- it counts raw length, not
stripped length) ship silently: `validate_petition_json({"arguments":
[{"topic_id": "   ", ...}]})` passed validation with no error, in every
test run all session, because nothing ever called it with exactly this
input. Every module in this package other than this one had a dedicated
test file; this was the blind spot.
"""
import pytest

from rfe_response_builder.schemas import SchemaValidationError, validate_evidence_json, validate_petition_json


# --- validate_petition_json ------------------------------------------------------

def test_valid_petition_passes_without_raising():
    validate_petition_json({"arguments": [{"topic_id": "t1", "text": "some text", "source_ref": "p. 1"}]})


def test_empty_arguments_list_is_valid():
    validate_petition_json({"arguments": []})


def test_petition_missing_arguments_key_raises():
    with pytest.raises(SchemaValidationError):
        validate_petition_json({})


def test_petition_arguments_not_a_list_raises():
    with pytest.raises(SchemaValidationError):
        validate_petition_json({"arguments": "not a list"})


def test_petition_argument_missing_required_field_raises():
    with pytest.raises(SchemaValidationError):
        validate_petition_json({"arguments": [{"topic_id": "t1", "text": "x"}]})  # missing source_ref


def test_petition_argument_with_wrong_type_raises():
    with pytest.raises(SchemaValidationError):
        validate_petition_json({"arguments": [{"topic_id": 123, "text": "x", "source_ref": "p. 1"}]})


def test_petition_argument_with_whitespace_only_field_raises():
    """The specific bug this test file exists to catch: jsonschema's
    minLength counts raw string length, so a whitespace-only string like
    "   " (length 3) satisfies minLength:1 even though it has no real
    content. The schema must also enforce a non-whitespace pattern."""
    with pytest.raises(SchemaValidationError):
        validate_petition_json({"arguments": [{"topic_id": "   ", "text": "x", "source_ref": "p. 1"}]})


def test_petition_argument_with_empty_string_field_raises():
    with pytest.raises(SchemaValidationError):
        validate_petition_json({"arguments": [{"topic_id": "", "text": "x", "source_ref": "p. 1"}]})


def test_petition_error_message_is_readable_and_per_field():
    try:
        validate_petition_json({"arguments": [{"topic_id": "t1", "text": "x"}]})
        assert False, "expected SchemaValidationError"
    except SchemaValidationError as e:
        assert "source_ref" in str(e)
        assert e.file_kind == "petition"
        assert len(e.problems) >= 1


# --- validate_evidence_json --------------------------------------------------

def test_valid_evidence_catalog_passes_without_raising():
    validate_evidence_json({"entries": [{"topic_id": "t1", "description": "x", "exhibit_label": "Exhibit A"}]})


def test_empty_entries_list_is_valid():
    validate_evidence_json({"entries": []})


def test_evidence_missing_entries_key_raises():
    with pytest.raises(SchemaValidationError):
        validate_evidence_json({})


def test_evidence_entry_missing_required_field_raises():
    with pytest.raises(SchemaValidationError):
        validate_evidence_json({"entries": [{"topic_id": "t1", "description": "x"}]})  # missing exhibit_label


def test_evidence_entry_with_whitespace_only_field_raises():
    with pytest.raises(SchemaValidationError):
        validate_evidence_json({"entries": [{"topic_id": "t1", "description": "   ", "exhibit_label": "Exhibit A"}]})


def test_evidence_error_message_is_readable():
    try:
        validate_evidence_json({"entries": [{"topic_id": "t1", "description": "x"}]})
        assert False, "expected SchemaValidationError"
    except SchemaValidationError as e:
        assert "exhibit_label" in str(e)
        assert e.file_kind == "evidence catalog"


# --- fallback path (jsonschema not installed) -------------------------------------

def test_fallback_structural_validation_accepts_valid_petition(monkeypatch):
    """Simulates jsonschema being unavailable -- validate_petition_json
    must still work correctly via the dependency-light fallback."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ImportError("simulated: jsonschema not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    validate_petition_json({"arguments": [{"topic_id": "t1", "text": "x", "source_ref": "p. 1"}]})


def test_fallback_structural_validation_rejects_whitespace_only_field(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ImportError("simulated: jsonschema not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SchemaValidationError):
        validate_petition_json({"arguments": [{"topic_id": "   ", "text": "x", "source_ref": "p. 1"}]})


def test_fallback_structural_validation_rejects_non_dict_root(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ImportError("simulated: jsonschema not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(SchemaValidationError):
        validate_petition_json(["not", "a", "dict"])
