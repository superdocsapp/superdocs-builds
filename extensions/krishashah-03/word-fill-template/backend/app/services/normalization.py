import re
from datetime import date
from typing import Any, Optional

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_TRUE_WORDS = {"true", "yes", "y", "1", "remote", "wfh", "work from home"}
_FALSE_WORDS = {"false", "no", "n", "0", "onsite", "on-site", "office", "in-office"}


class NormalizationError(Exception):
    pass


def normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise NormalizationError("Boolean value cannot be normalized as a number.")
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return None

    lowered = text.lower()
    multiplier = None
    if "crore" in lowered:
        multiplier = 10_000_000
        lowered = lowered.replace("crore", "")
    elif "lpa" in lowered or "lakh" in lowered or "lac" in lowered:
        multiplier = 100_000
        lowered = lowered.replace("lpa", "").replace("lakh", "").replace("lac", "")

    lowered = lowered.replace("per annum", "").replace("p.a.", "").replace("pa", "")
    lowered = re.sub(r"[₹$,\s]", "", lowered)

    match = re.search(r"-?\d+(\.\d+)?", lowered)
    if not match:
        raise NormalizationError(f"Could not parse a number from '{value}'.")

    number = float(match.group())
    if multiplier:
        number *= multiplier
    return number


def normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    if not text:
        return None

    iso_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if iso_match:
        try:
            return date(*(int(part) for part in iso_match.groups())).isoformat()
        except ValueError as exc:
            raise NormalizationError(f"'{value}' is not a valid date.") from exc

    cleaned = re.sub(r"\s+", " ", text.replace(",", " ")).strip()

    month_first = re.match(r"^([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})$", cleaned)
    day_first = re.match(r"^(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})$", cleaned)

    if month_first:
        month_name, day_str, year_str = month_first.groups()
    elif day_first:
        day_str, month_name, year_str = day_first.groups()
    else:
        slash_match = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", cleaned)
        if slash_match:
            day_str, month_str, year_str = slash_match.groups()
            try:
                return date(int(year_str), int(month_str), int(day_str)).isoformat()
            except ValueError as exc:
                raise NormalizationError(f"'{value}' is not a valid date.") from exc
        raise NormalizationError(f"Could not parse a date from '{value}'.")

    month = _MONTHS.get(month_name.strip().lower())
    if not month:
        raise NormalizationError(f"Unrecognized month in date '{value}'.")

    try:
        return date(int(year_str), month, int(day_str)).isoformat()
    except ValueError as exc:
        raise NormalizationError(f"'{value}' is not a valid date.") from exc


def normalize_boolean(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)

    text = str(value).strip().lower()
    if not text:
        return None
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    raise NormalizationError(f"Could not parse a boolean from '{value}'.")


_NORMALIZERS = {
    "string": normalize_string,
    "number": normalize_number,
    "date": normalize_date,
    "boolean": normalize_boolean,
}


def normalize_field(field_type: str, value: Any) -> Optional[Any]:
    normalizer = _NORMALIZERS.get(field_type, normalize_string)
    return normalizer(value)


def map_raw_keys_to_schema(raw: dict, field_keys: list[str]) -> dict[str, Any]:
    """Map a flat raw dict's keys onto declared schema field keys.

    A raw key matches a schema key by exact match, or - when the raw key has
    no namespace of its own - by matching the schema key's final path
    segment (e.g. raw key "ctc" matches schema key "employee.ctc").
    """
    leaf_to_schema_key: dict[str, str] = {}
    for key in field_keys:
        leaf = key.rsplit(".", 1)[-1].lower()
        leaf_to_schema_key.setdefault(leaf, key)

    schema_key_set = set(field_keys)
    mapped: dict[str, Any] = {}
    for raw_key, value in raw.items():
        if raw_key in schema_key_set:
            mapped[raw_key] = value
            continue
        leaf = raw_key.rsplit(".", 1)[-1].strip().lower()
        schema_key = leaf_to_schema_key.get(leaf)
        if schema_key:
            mapped[schema_key] = value
    return mapped


def normalize_record(raw: dict, field_schema: dict) -> tuple[dict[str, Any], dict[str, str]]:
    """Normalize a flat raw dict against a template's field schema.

    Returns (normalized_data, normalization_errors); normalization_errors
    maps field_key -> error message for values that could not be normalized.
    """
    mapped = map_raw_keys_to_schema(raw, list(field_schema.keys()))

    normalized: dict[str, Any] = {}
    errors: dict[str, str] = {}

    for field_key, field_def in field_schema.items():
        if field_key not in mapped:
            continue
        raw_value = mapped[field_key]
        if raw_value is None:
            continue

        field_type = field_def.get("type", "string") if isinstance(field_def, dict) else "string"
        try:
            normalized_value = normalize_field(field_type, raw_value)
        except NormalizationError as exc:
            errors[field_key] = str(exc)
            continue

        if normalized_value is not None:
            normalized[field_key] = normalized_value

    return normalized, errors
