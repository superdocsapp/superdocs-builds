"""Manifest Schema Validation and Strict Normalization Handler.

Implements strict completeness & fallback rules:
If any metadata field is missing or empty, explicitly mark it as "Not provided".
Never invent, hallucinate, or infer missing values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

FALLBACK_VALUE = "Not provided"

# Standard core metadata fields required for Model and System Cards
STANDARD_FIELDS = [
    "model_name",
    "version",
    "release_date",
    "model_type",
    "description",
    "intended_purpose",
    "limitations",
    "out_of_scope_uses",
    "maintenance_contact",
    "training_data_summary",
    "model_architecture",
    "ethical_considerations",
    "license",
    "citation",
    "hardware_and_compute",
    "author_organization",
]

# Field alias mappings to accommodate common naming variations
FIELD_ALIASES: Dict[str, List[str]] = {
    "intended_purpose": ["intended_use", "intended_uses", "purpose", "primary_uses"],
    "out_of_scope_uses": ["out_of_scope", "prohibited_uses", "non_goals"],
    "maintenance_contact": ["contact", "contact_info", "maintainer", "maintainers"],
    "training_data_summary": ["training_data", "dataset_summary", "training_dataset"],
    "ethical_considerations": ["safety_and_alignment", "ethics", "ethical_aspects", "safety_considerations"],
    "model_architecture": ["architecture", "model_details", "technical_specifications"],
    "hardware_and_compute": ["compute_infrastructure", "hardware", "environmental_impact"],
    "author_organization": ["organization", "authors", "developer", "institution"],
}


def _is_empty_or_blank(val: Any) -> bool:
    """Check if a value is None, empty string, whitespace only, or empty collection."""
    if val is None:
        return True
    if isinstance(val, str):
        return len(val.strip()) == 0
    if isinstance(val, (list, tuple, set)):
        if len(val) == 0:
            return True
        # Check if all items inside are empty
        return all(_is_empty_or_blank(item) for item in val)
    if isinstance(val, dict):
        if len(val) == 0:
            return True
        return all(_is_empty_or_blank(v) for v in val.values())
    return False


def _clean_value(val: Any) -> Any:
    """Recursively clean value, replacing empty elements with FALLBACK_VALUE."""
    if _is_empty_or_blank(val):
        return FALLBACK_VALUE

    if isinstance(val, str):
        cleaned = val.strip()
        return cleaned if cleaned else FALLBACK_VALUE

    if isinstance(val, list):
        filtered = [_clean_value(item) for item in val if not _is_empty_or_blank(item)]
        return filtered if filtered else FALLBACK_VALUE

    if isinstance(val, dict):
        cleaned_dict = {}
        for k, v in val.items():
            if _is_empty_or_blank(v):
                cleaned_dict[k] = FALLBACK_VALUE
            else:
                cleaned_dict[k] = _clean_value(v)
        return cleaned_dict if cleaned_dict else FALLBACK_VALUE

    return val


class ManifestNormalizer:
    """Validates and normalizes model manifest data with strict completeness rules."""

    def __init__(self, schema_path: Optional[Union[str, Path]] = None) -> None:
        """Initialize the normalizer with optional schema path."""
        if schema_path is None:
            default_schema = Path(__file__).resolve().parent.parent / "schemas" / "manifest_schema.json"
            if default_schema.exists():
                schema_path = default_schema
        
        self.schema_path = Path(schema_path) if schema_path else None
        self.schema: Optional[Dict[str, Any]] = None
        if self.schema_path and self.schema_path.exists():
            with open(self.schema_path, "r", encoding="utf-8") as f:
                self.schema = json.load(f)

    def validate(self, raw_data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate raw manifest data against JSON schema.
        
        Returns:
            (is_valid, list_of_error_messages)
        """
        if not HAS_JSONSCHEMA or self.schema is None:
            return True, []

        validator = jsonschema.Draft7Validator(self.schema)
        errors = [err.message for err in validator.iter_errors(raw_data)]
        return len(errors) == 0, errors

    def normalize(self, raw_manifest: Union[Dict[str, Any], str, Path]) -> Dict[str, Any]:
        """Normalize manifest dictionary or file to guarantee completeness.
        
        Every standard key is guaranteed to exist.
        Any missing or empty value is strictly set to 'Not provided'.
        Never invents or hallucinates any values.
        """
        if isinstance(raw_manifest, (str, Path)):
            manifest_path = Path(raw_manifest)
            if manifest_path.is_file():
                with open(manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = json.loads(str(raw_manifest))
        elif isinstance(raw_manifest, dict):
            data = dict(raw_manifest)
        else:
            raise ValueError(f"Unsupported manifest input type: {type(raw_manifest)}")

        normalized: Dict[str, Any] = {}

        # Resolve aliases into canonical fields first
        working_data = dict(data)
        for canonical, aliases in FIELD_ALIASES.items():
            if canonical not in working_data or _is_empty_or_blank(working_data[canonical]):
                for alias in aliases:
                    if alias in working_data and not _is_empty_or_blank(working_data[alias]):
                        working_data[canonical] = working_data[alias]
                        break

        # Process all standard fields
        for field in STANDARD_FIELDS:
            raw_val = working_data.get(field)
            normalized[field] = _clean_value(raw_val)

        # Preserve any additional custom fields provided by the user, cleaning them
        for k, v in working_data.items():
            if k not in normalized:
                normalized[k] = _clean_value(v)

        return normalized

    @staticmethod
    def format_markdown_field(value: Any, bullet_prefix: str = "- ") -> str:
        """Format normalized value into human-readable markdown content.
        
        Returns 'Not provided' if value is FALLBACK_VALUE or empty.
        """
        if value is None or value == FALLBACK_VALUE:
            return FALLBACK_VALUE

        if isinstance(value, str):
            val_clean = value.strip()
            return val_clean if val_clean else FALLBACK_VALUE

        if isinstance(value, list):
            if not value:
                return FALLBACK_VALUE
            formatted_items = []
            for item in value:
                if isinstance(item, dict):
                    sub_items = [f"{k}: {v}" for k, v in item.items() if v != FALLBACK_VALUE]
                    formatted_items.append(f"{bullet_prefix}{', '.join(sub_items)}")
                else:
                    item_str = str(item).strip()
                    if item_str and item_str != FALLBACK_VALUE:
                        formatted_items.append(f"{bullet_prefix}{item_str}")
            return "\n".join(formatted_items) if formatted_items else FALLBACK_VALUE

        if isinstance(value, dict):
            if not value:
                return FALLBACK_VALUE
            formatted_lines = []
            for k, v in value.items():
                label = k.replace("_", " ").title()
                if isinstance(v, list):
                    sub_bullets = ", ".join(str(x) for x in v if str(x) != FALLBACK_VALUE)
                    formatted_lines.append(f"{bullet_prefix}**{label}**: {sub_bullets if sub_bullets else FALLBACK_VALUE}")
                elif isinstance(v, dict):
                    sub_str = "; ".join(f"{sk}: {sv}" for sk, sv in v.items())
                    formatted_lines.append(f"{bullet_prefix}**{label}**: {sub_str if sub_str else FALLBACK_VALUE}")
                else:
                    formatted_lines.append(f"{bullet_prefix}**{label}**: {v}")
            return "\n".join(formatted_lines) if formatted_lines else FALLBACK_VALUE

        return str(value)
