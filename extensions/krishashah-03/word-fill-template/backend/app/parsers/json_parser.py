import json
from typing import Any


class JSONParseError(Exception):
    pass


def parse_json_input(content: Any) -> dict[str, Any]:
    """Deterministically parse JSON input into a flat dict of field paths to raw values.

    Accepts either an already-parsed dict/list or a JSON string. Nested objects
    are flattened using dot notation, e.g. {"employee": {"name": "X"}} becomes
    {"employee.name": "X"}.
    """
    if isinstance(content, str):
        text = content.strip()
        if not text:
            raise JSONParseError("JSON input is empty.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise JSONParseError(f"Invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno}).") from exc
    elif isinstance(content, (dict, list)):
        data = content
    else:
        raise JSONParseError("JSON input must be an object, array, or JSON string.")

    if not isinstance(data, dict):
        raise JSONParseError("Top-level JSON input must be an object.")
    if not data:
        raise JSONParseError("JSON input is empty.")

    return _flatten(data)


def _flatten(obj: dict, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and value:
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat
