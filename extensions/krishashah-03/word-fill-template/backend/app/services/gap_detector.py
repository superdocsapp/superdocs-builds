def detect_gaps(normalized_data: dict, field_schema: dict) -> list[dict]:
    """Compare normalized data against the template schema for missing required fields.

    Never invents values - a gap is reported whenever a required field has no
    normalized value, and the caller must surface it for the user to resolve.
    """
    gaps: list[dict] = []
    for field_key, field_def in field_schema.items():
        required = bool(field_def.get("required")) if isinstance(field_def, dict) else False
        if not required:
            continue
        if normalized_data.get(field_key) is None:
            gaps.append({"field": field_key, "reason": "Required field is missing"})
    return gaps
