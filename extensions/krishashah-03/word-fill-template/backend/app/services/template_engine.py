from app.services.condition_engine import evaluate_condition

READY = "ready"
MISSING = "missing"
UNRESOLVED = "unresolved"


def resolve_conditions(conditions: list[dict], normalized_data: dict) -> list[dict]:
    return [
        evaluate_condition(
            condition["condition_key"],
            condition.get("operator", "=="),
            condition.get("expected_value", True),
            condition.get("action", "include"),
            normalized_data,
        ).to_dict()
        for condition in conditions
    ]


def build_proposed_changes(field_schema: dict, normalized_data: dict, gap_fields: set[str]) -> list[dict]:
    """Resolve each schema field's placeholder against normalized data.

    A field with a gap, or with no value at all, is never filled in with a
    guess - it is reported as "missing" so the document is left untouched
    for that field until the user supplies a value.
    """
    changes = []
    for field_key in field_schema:
        placeholder = "{{" + field_key + "}}"
        value = normalized_data.get(field_key)

        if field_key in gap_fields or value is None:
            status = MISSING
        else:
            status = READY

        changes.append(
            {
                "field": field_key,
                "placeholder": placeholder,
                "current_value": None,
                "proposed_value": value,
                "status": status,
            }
        )
    return changes


def build_template_result(
    field_schema: dict, conditions: list[dict], normalized_data: dict, gaps: list[dict]
) -> dict:
    """Generic, schema-driven resolution step shared by every template category.

    Nothing here is specific to HR/salary/employee data - the field names,
    types, and conditions all come from the template's own schema.json.
    """
    gap_fields = {gap["field"] for gap in gaps}
    return {
        "proposed_changes": build_proposed_changes(field_schema, normalized_data, gap_fields),
        "conditions": resolve_conditions(conditions, normalized_data),
    }
