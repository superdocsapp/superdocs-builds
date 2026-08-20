from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .models import SpecChange


def stable_id(*parts: object) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:18]


def load_spec(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    value = yaml.safe_load(text)
    if not isinstance(value, dict) or "openapi" not in value:
        raise ValueError(f"not an OpenAPI document: {path}")
    return value


def property_map(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    schemas = spec.get("components", {}).get("schemas", {})
    for schema_name, schema in schemas.items():
        for property_name, definition in schema.get("properties", {}).items():
            result[f"components.schemas.{schema_name}.properties.{property_name}"] = definition
    return result


def operation_map(spec: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for path, path_item in spec.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}:
                result[f"paths.{path}.{method.lower()}"] = operation
    return result


def comparable(definition: dict[str, Any]) -> dict[str, Any]:
    # Descriptions are evidence, not noise: without them, two unrelated string
    # fields can look like equally plausible rename targets.
    return {key: value for key, value in definition.items() if key not in {"deprecated", "title"}}


def diff_specs(previous: dict[str, Any], current: dict[str, Any]) -> list[SpecChange]:
    changes: list[SpecChange] = []
    old_properties, new_properties = property_map(previous), property_map(current)
    removed = set(old_properties) - set(new_properties)
    added = set(new_properties) - set(old_properties)
    consumed_added: set[str] = set()
    consumed_removed: set[str] = set()

    for old_location in sorted(removed):
        old_parent = old_location.rsplit(".", 1)[0]
        candidates = [
            location for location in added
            if location.rsplit(".", 1)[0] == old_parent
            and comparable(old_properties[old_location]) == comparable(new_properties[location])
        ]
        if len(candidates) == 1:
            new_location = candidates[0]
            changes.append(
                SpecChange(
                    id=stable_id("renamed", old_location, new_location), kind="renamed", location=old_parent,
                    before=old_location.rsplit(".", 1)[1], after=new_location.rsplit(".", 1)[1], confidence=0.96,
                    explanation="One removed field and one structurally identical added field share the same schema.",
                )
            )
            consumed_removed.add(old_location); consumed_added.add(new_location)
        elif len(candidates) > 1:
            changes.append(
                SpecChange(
                    id=stable_id("ambiguous", old_location, candidates), kind="changed", location=old_location,
                    before=old_location.rsplit(".", 1)[1], after=[item.rsplit(".", 1)[1] for item in candidates], confidence=0.35,
                    explanation="Multiple structurally plausible rename targets exist; a writer must decide.",
                )
            )
            consumed_removed.add(old_location); consumed_added.update(candidates)

    for location in sorted(removed - consumed_removed):
        changes.append(SpecChange(stable_id("removed", location), "removed", location, old_properties[location], None, 1.0, "Field is absent from the current specification."))
    for location in sorted(added - consumed_added):
        changes.append(SpecChange(stable_id("added", location), "added", location, None, new_properties[location], 1.0, "Field is new in the current specification."))

    for location in sorted(set(old_properties) & set(new_properties)):
        before, after = old_properties[location], new_properties[location]
        if before != after:
            kind = "deprecated" if not before.get("deprecated") and after.get("deprecated") else "changed"
            changes.append(SpecChange(stable_id(kind, location, before, after), kind, location, before, after, 1.0, "Field definition changed."))

    old_operations, new_operations = operation_map(previous), operation_map(current)
    for location in sorted(set(old_operations) - set(new_operations)):
        changes.append(SpecChange(stable_id("removed", location), "removed", location, old_operations[location], None, 1.0, "Operation is absent from the current specification."))
    for location in sorted(set(new_operations) - set(old_operations)):
        changes.append(SpecChange(stable_id("added", location), "added", location, None, new_operations[location], 1.0, "Operation is new in the current specification."))
    return changes
