"""
JSON Schema validation for the two structured input files this package
accepts from a user (petition-arguments JSON, new-evidence-catalog JSON).

Before this module, a malformed upload (missing key, wrong type, extra
whitespace-only file) surfaced as a raw `KeyError` or `TypeError` from
deep inside `load_petition`/`load_new_evidence_catalog`/the webapp's
`_load_petition_from_text`, which is unreadable to the paralegal or
attorney who uploaded the file. `validate_petition_json` and
`validate_evidence_json` run a real JSON Schema check first and raise
`SchemaValidationError` with a flat list of human-readable, per-field
problems instead.

Kept dependency-light: uses `jsonschema` if installed (richer, standard
error paths), and falls back to a hand-rolled structural check if it
isn't, so this degrades gracefully rather than becoming a hard
requirement of a package that was previously stdlib-only for its domain
logic.
"""
from __future__ import annotations

from typing import Any

PETITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["arguments"],
    "properties": {
        "arguments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["topic_id", "text", "source_ref"],
                "properties": {
                    "topic_id": {"type": "string", "minLength": 1, "pattern": r"\S"},
                    "text": {"type": "string", "minLength": 1, "pattern": r"\S"},
                    "source_ref": {"type": "string", "minLength": 1, "pattern": r"\S"},
                },
            },
        }
    },
}

EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["entries"],
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["topic_id", "description", "exhibit_label"],
                "properties": {
                    "topic_id": {"type": "string", "minLength": 1, "pattern": r"\S"},
                    "description": {"type": "string", "minLength": 1, "pattern": r"\S"},
                    "exhibit_label": {"type": "string", "minLength": 1, "pattern": r"\S"},
                },
            },
        }
    },
}


class SchemaValidationError(ValueError):
    """Raised with a flat list of human-readable, per-field problems."""

    def __init__(self, file_kind: str, problems: list[str]):
        self.file_kind = file_kind
        self.problems = problems
        message = f"{file_kind} file failed validation:\n" + "\n".join(f"  - {p}" for p in problems)
        super().__init__(message)


def _validate_with_jsonschema(data: Any, schema: dict[str, Any], file_kind: str) -> None:
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        problems = []
        for e in errors:
            path = "/".join(str(p) for p in e.path) or "(root)"
            problems.append(f"{path}: {e.message}")
        raise SchemaValidationError(file_kind, problems)


def _validate_structurally(data: Any, top_key: str, item_keys: list[str], file_kind: str) -> None:
    """Fallback used only when `jsonschema` isn't installed. Covers the
    same required-shape checks with plain Python -- less precise error
    text than jsonschema's, but never leaves validation entirely off."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise SchemaValidationError(file_kind, ["(root): must be a JSON object"])
    items = data.get(top_key)
    if not isinstance(items, list):
        raise SchemaValidationError(file_kind, [f"{top_key}: must be an array"])
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"{top_key}[{i}]: must be an object")
            continue
        for key in item_keys:
            val = item.get(key)
            if not isinstance(val, str) or not val.strip():
                problems.append(f"{top_key}[{i}].{key}: required non-empty string")
    if problems:
        raise SchemaValidationError(file_kind, problems)


def validate_petition_json(data: Any) -> None:
    """Raises SchemaValidationError with a readable problem list if `data`
    (already `json.loads`-ed) doesn't match the petition-arguments shape.
    Returns None (does not mutate `data`) on success."""
    try:
        _validate_with_jsonschema(data, PETITION_SCHEMA, "petition")
    except ImportError:
        _validate_structurally(data, "arguments", ["topic_id", "text", "source_ref"], "petition")


def validate_evidence_json(data: Any) -> None:
    try:
        _validate_with_jsonschema(data, EVIDENCE_SCHEMA, "evidence catalog")
    except ImportError:
        _validate_structurally(data, "entries", ["topic_id", "description", "exhibit_label"], "evidence catalog")
