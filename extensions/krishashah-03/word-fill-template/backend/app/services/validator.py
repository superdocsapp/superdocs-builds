_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "date": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
}


def validate_record(normalized_data: dict, field_schema: dict) -> list[dict]:
    """Validate that each present field's value matches its declared schema type.

    Presence of required fields is handled separately by gap detection.
    """
    issues: list[dict] = []
    for field_key, value in normalized_data.items():
        field_def = field_schema.get(field_key)
        if field_def is None:
            continue

        field_type = field_def.get("type", "string") if isinstance(field_def, dict) else "string"
        checker = _TYPE_CHECKS.get(field_type)
        if checker and not checker(value):
            issues.append({"field": field_key, "message": f"Expected a {field_type} value."})

    return issues
