from dataclasses import dataclass
from typing import Any, Optional

_OPERATORS = {
    "==": lambda a, b: a == b,
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@dataclass
class ConditionResult:
    condition_key: str
    action: str
    resolved: bool
    include: Optional[bool]

    def to_dict(self) -> dict:
        return {
            "condition_key": self.condition_key,
            "action": self.action,
            "resolved": self.resolved,
            "include": self.include,
        }


def evaluate_condition(
    condition_key: str,
    operator: str,
    expected_value: Any,
    action: str,
    data: dict,
) -> ConditionResult:
    """Deterministically evaluate one condition against normalized data.

    If the referenced field is missing or null, the condition is unresolved
    rather than guessed - callers must surface this to the user.
    """
    if condition_key not in data or data.get(condition_key) is None:
        return ConditionResult(condition_key, action, resolved=False, include=None)

    comparator = _OPERATORS.get(operator)
    if comparator is None:
        raise ValueError(f"Unsupported condition operator: {operator}")

    satisfied = comparator(data[condition_key], expected_value)

    if action == "include":
        include = satisfied
    elif action == "exclude":
        include = not satisfied
    else:
        raise ValueError(f"Unsupported condition action: {action}")

    return ConditionResult(condition_key, action, resolved=True, include=include)


def evaluate_conditions(conditions: list[dict], data: dict) -> list[ConditionResult]:
    return [
        evaluate_condition(
            condition["condition_key"],
            condition.get("operator", "=="),
            condition.get("expected_value"),
            condition.get("action", "include"),
            data,
        )
        for condition in conditions
    ]
