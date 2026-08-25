"""Generic reusable metrics for evaluating inferred templates."""

from __future__ import annotations

import re
from collections.abc import Iterable
from itertools import combinations
from typing import Any


def normalize_name(value: Any) -> str:
    """Normalize identifier strings for stable, benchmark-agnostic comparisons."""
    text = str(value or "").strip().lower()
    text = text.replace("/", "_")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _normalize_operator(operator: str) -> str:
    """Normalize operator names for comparison.

    Converts different representations to canonical form:
    - "equals" -> "=="
    - "is" -> "=="
    - "eq" -> "=="
    """
    op = str(operator or "").lower().strip()
    if op in ("equals", "is", "eq"):
        return "=="
    return op


def canonical_condition(condition: Any) -> str:
    """Canonicalize a rule condition into a stable field/operator/value string.

    Handles both dict format ({"field": ..., "operator": ..., "value": ...})
    and string format (e.g., "field == value", "field in [values]").
    """
    if condition is None:
        return ""
    if isinstance(condition, str):
        # Try to parse string condition into field|operator|value format
        text = condition.strip()

        # Pattern: field OPERATOR value (handles ==, !=, in, etc.)
        # e.g., "employment_type == 'Remote'" or "department == Engineering"
        match = re.search(
            r"^([a-zA-Z_][a-zA-Z0-9_']*)\s*(==|!=|in|>=|<=|>|<|contains|is|equals)\s*(.+)$",
            text,
            re.IGNORECASE
        )
        if match:
            field = normalize_name(match.group(1))
            operator = _normalize_operator(match.group(2))
            value_str = match.group(3).strip()
            # Remove quotes and normalize the value
            value_normalized = normalize_name(value_str)
            return f"{field}|{operator}|{value_normalized}"

        # Fallback: just normalize the whole string
        compact = re.sub(r"\s+", " ", text)
        return compact.lower()

    if isinstance(condition, dict):
        field = str(condition.get("field") or condition.get("name") or condition.get("attribute") or "").strip()
        operator = _normalize_operator(condition.get("operator") or condition.get("op") or "")
        value = condition.get("value")
        if isinstance(value, (list, tuple, set)):
            value_text = ",".join(str(item) for item in value)
        else:
            value_text = str(value or "").strip()
        return f"{normalize_name(field)}|{operator}|{normalize_name(value_text)}" if field else f"{operator}|{normalize_name(value_text)}"
    return normalize_name(condition)


def extract_section_names(values: Any) -> list[str]:
    """Return normalized section names from structured or plain values."""
    items: list[str] = []
    if values is None:
        return items
    if isinstance(values, str):
        values = [values]
    elif not isinstance(values, Iterable):
        values = [values]

    for item in values:
        if item is None:
            continue
        if isinstance(item, dict):
            candidate = (
                item.get("title_or_pattern")
                or item.get("section_name")
                or item.get("name")
                or item.get("title")
                or item.get("heading_text")
                or item.get("target_section")
            )
        else:
            candidate = item
        normalized = normalize_name(candidate)
        if normalized:
            items.append(normalized)
    return items


def extract_variable_names(values: Any) -> list[str]:
    """Return normalized variable names from structured or plain values."""
    items: list[str] = []
    if values is None:
        return items
    if isinstance(values, str):
        values = [values]
    elif not isinstance(values, Iterable):
        values = [values]

    for item in values:
        if item is None:
            continue
        if isinstance(item, dict):
            candidate = item.get("variable_name") or item.get("name") or item.get("variable")
        else:
            candidate = item
        normalized = normalize_name(candidate)
        if normalized:
            items.append(normalized)
    return items


def extract_variable_metadata(values: Any) -> dict[str, dict[str, Any]]:
    """Map normalized variable names to their metadata for type-aware scoring."""
    metadata: dict[str, dict[str, Any]] = {}
    if values is None:
        return metadata
    if isinstance(values, dict):
        iterable = values.values()
    else:
        iterable = values

    for item in iterable:
        if item is None:
            continue
        if isinstance(item, dict):
            name = item.get("variable_name") or item.get("name") or item.get("variable")
            if not name:
                continue
            normalized = normalize_name(name)
            metadata[normalized] = {
                "raw_name": str(name),
                "type": str(item.get("inferred_type") or item.get("type") or "").strip(),
                "is_enum": bool(item.get("is_enum")),
                "enum_values": item.get("enum_values") or [],
            }
        else:
            normalized = normalize_name(item)
            metadata[normalized] = {"raw_name": str(item), "type": "", "is_enum": False, "enum_values": []}
    return metadata


def section_f1_score(expected_sections: Any, predicted_sections: Any) -> float:
    """Compute section precision/recall/F1 using normalized names."""
    expected = set(extract_section_names(expected_sections))
    predicted = set(extract_section_names(predicted_sections))
    if not expected and not predicted:
        return 1.0
    true_positives = len(expected & predicted)
    false_positives = len(predicted - expected)
    false_negatives = len(expected - predicted)
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0
    if precision + recall == 0.0:
        return 0.0
    return (2.0 * precision * recall) / (precision + recall)


def section_order_score(expected_order: Any, predicted_order: Any) -> float:
    """Score relative section order using pairwise precedence accuracy."""
    expected = extract_section_names(expected_order)
    predicted = extract_section_names(predicted_order)
    if not expected:
        return 1.0 if not predicted else 0.0
    relevant = [item for item in expected if item in set(predicted)]
    if len(relevant) < 2:
        return 1.0 if len(relevant) == len(expected) else 0.0
    expected_positions = {name: index for index, name in enumerate(expected)}
    predicted_positions = {name: index for index, name in enumerate(predicted)}
    correct = 0
    total = 0
    for left, right in combinations(relevant, 2):
        if left not in predicted_positions or right not in predicted_positions:
            continue
        expected_ordered = expected_positions[left] < expected_positions[right]
        predicted_ordered = predicted_positions[left] < predicted_positions[right]
        total += 1
        if expected_ordered == predicted_ordered:
            correct += 1
    if total == 0:
        return 1.0
    return correct / total


def conditional_rule_score(expected_rules: Any, predicted_rules: Any) -> float:
    """Compare conditional rules via canonical field/operator/value equality."""
    expected = _to_rule_map(expected_rules)
    predicted = _to_rule_map(predicted_rules)
    if not expected and not predicted:
        return 1.0
    matched_sections = set(expected) & set(predicted)
    if not matched_sections:
        return 0.0
    score_total = 0.0
    for section in sorted(matched_sections):
        expected_rule = expected[section]
        predicted_rule = predicted[section]
        expected_condition = canonical_condition(expected_rule)
        predicted_condition = canonical_condition(predicted_rule)
        if expected_condition == predicted_condition:
            score_total += 1.0
        else:
            expected_field = _condition_field(expected_rule)
            predicted_field = _condition_field(predicted_rule)
            if expected_field and predicted_field and expected_field == predicted_field:
                score_total += 0.5
    return score_total / len(expected) if expected else 0.0


def variable_score(expected_variables: Any, predicted_variables: Any) -> float:
    """Compute variable quality using normalized names and type agreement."""
    expected_names = set(extract_variable_names(expected_variables))
    predicted_names = set(extract_variable_names(predicted_variables))
    if not expected_names and not predicted_names:
        return 1.0
    true_positives = len(expected_names & predicted_names)
    false_positives = len(predicted_names - expected_names)
    false_negatives = len(expected_names - predicted_names)
    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else 0.0
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else 0.0
    name_f1 = (2.0 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    expected_metadata = extract_variable_metadata(expected_variables)
    predicted_metadata = extract_variable_metadata(predicted_variables)
    type_matches = 0
    matched = 0
    for name in sorted(expected_names & predicted_names):
        matched += 1
        expected_type = str(expected_metadata.get(name, {}).get("type") or "").strip().lower()
        predicted_type = str(predicted_metadata.get(name, {}).get("type") or "").strip().lower()
        if expected_type and predicted_type and expected_type == predicted_type:
            type_matches += 1
        elif not expected_type or not predicted_type:
            type_matches += 0.5
    type_agreement = type_matches / matched if matched else 0.0
    return (0.7 * name_f1) + (0.3 * type_agreement)


def _to_rule_map(rules: Any) -> dict[str, Any]:
    if rules is None:
        return {}
    if isinstance(rules, dict):
        items = []
        for key, value in rules.items():
            if isinstance(value, dict):
                section_name = value.get("target_section") or value.get("section_name") or key
                item = {"target_section": section_name, **value}
            else:
                item = {"target_section": key, "condition": value}
            items.append(item)
        rules = items

    result: dict[str, Any] = {}
    for rule in rules:
        if isinstance(rule, dict):
            section = str(rule.get("target_section") or rule.get("section_name") or rule.get("name") or "").strip()
            if not section:
                continue
            result[normalize_name(section)] = rule.get("condition") or rule
    return result


def _condition_field(condition: Any) -> str:
    if condition is None:
        return ""
    if isinstance(condition, dict):
        return normalize_name(str(condition.get("field") or condition.get("name") or condition.get("attribute") or ""))
    if isinstance(condition, str):
        match = re.search(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*(==|!=|>=|<=|>|<|in)" , condition)
        if match:
            return normalize_name(match.group(1))
        return normalize_name(condition)
    return normalize_name(condition)
