"""JSON helpers with repair for imperfect LLM output."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


def strip_code_fences(text: str) -> str:
    text = text.strip()
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return text


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _escape_raw_newlines_in_strings(text: str) -> str:
    """Escape unescaped newlines that appear inside JSON string literals."""
    result: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if escaped:
            result.append(ch)
            escaped = False
            continue
        if ch == "\\" and in_string:
            result.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string and ch in ("\n", "\r"):
            result.append("\\n" if ch == "\n" else "\\r")
            continue
        result.append(ch)
    return "".join(result)


def _balanced_object_slice(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _try_load(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def extract_failed_generation(exc: BaseException) -> str | None:
    """Pull Groq/OpenAI `failed_generation` payload out of error text/body."""
    text = str(exc)
    # Common pattern: ...'failed_generation': '{...}'...
    match = re.search(r"failed_generation['\"]?\s*[:=]\s*['\"](\{[\s\S]*)", text)
    if match:
        candidate = match.group(1)
        # Trim trailing quote / brace noise from repr
        if candidate.endswith("'}") or candidate.endswith('"}'):
            candidate = candidate[:-2]
        elif candidate.endswith("'") or candidate.endswith('"'):
            candidate = candidate[:-1]
        return candidate

    # dict-like body embedded in message
    try:
        start = text.index("{")
        blob = text[start:]
        # Prefer nested failed_generation via loose search
        nested = re.search(
            r"['\"]failed_generation['\"]\s*:\s*['\"]([\s\S]+?)['\"]\s*[,}]",
            blob,
        )
        if nested:
            return nested.group(1).encode("utf-8").decode("unicode_escape")
    except Exception:  # noqa: BLE001
        pass
    return None


def _close_open_containers(fragment: str) -> str:
    """Close unclosed { and [ while respecting strings."""
    in_string = False
    escaped = False
    stack: list[str] = []
    for ch in fragment:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{":
            stack.pop()
        elif ch == "]" and stack and stack[-1] == "[":
            stack.pop()
    closing = "".join("}" if opener == "{" else "]" for opener in reversed(stack))
    return fragment + closing


def coerce_truncated_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort salvage of truncated JSON objects from failed_generation."""
    cleaned = strip_code_fences(text).strip()
    data = _try_load(cleaned)
    if data is not None:
        return data

    repaired = _remove_trailing_commas(_escape_raw_newlines_in_strings(cleaned))
    data = _try_load(repaired)
    if data is not None:
        return data

    if "{" not in cleaned:
        return None

    fragment = repaired if repaired.startswith("{") else cleaned[cleaned.find("{") :]

    # Mid-string truncation: drop incomplete trailing string + dangling key
    if fragment.count('"') % 2 == 1:
        fragment = fragment.rsplit('"', 1)[0]
        fragment = re.sub(r',?\s*"[^"]*"\s*:\s*$', "", fragment)
        fragment = re.sub(r",\s*$", "", fragment)

    fragment = re.sub(r",\s*\{\s*$", "", fragment)
    fragment = re.sub(r",\s*$", "", fragment)
    fragment = _remove_trailing_commas(fragment)
    fragment = _close_open_containers(fragment)
    fragment = _remove_trailing_commas(fragment)
    return _try_load(fragment)


def _looks_like_json_schema(data: dict[str, Any]) -> bool:
    """True when the model echoed a JSON Schema instead of instance data."""
    markers = {"$defs", "$schema", "definitions", "properties", "additionalProperties"}
    return bool(markers.intersection(data.keys())) and data.get("type") == "object"


def example_payload_for_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Build a tiny example object so small models don't echo the JSON Schema."""
    example: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        annotation = field.annotation
        origin = getattr(annotation, "__origin__", None)
        if annotation is str or annotation == str:
            example[name] = f"example_{name}"
        elif annotation is bool or annotation == bool:
            example[name] = False
        elif annotation is int or annotation == int:
            example[name] = 0
        elif origin is list:
            example[name] = []
        elif origin is dict:
            example[name] = {}
        else:
            # Optional / Union / nested models — keep empty-ish defaults
            default = field.default
            if default is not None and default is not ...:
                try:
                    example[name] = default
                    continue
                except Exception:  # noqa: BLE001
                    pass
            if field.default_factory is not None:
                try:
                    example[name] = field.default_factory()
                    continue
                except Exception:  # noqa: BLE001
                    pass
            example[name] = None
    return example


def extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort extract of a JSON object from model text."""
    cleaned = strip_code_fences(text)
    candidates = [cleaned]

    sliced = _balanced_object_slice(cleaned)
    if sliced and sliced not in candidates:
        candidates.append(sliced)

    for candidate in list(candidates):
        repaired = _remove_trailing_commas(_escape_raw_newlines_in_strings(candidate))
        if repaired not in candidates:
            candidates.append(repaired)

    last_error: Exception | None = None
    for candidate in candidates:
        data = _try_load(candidate)
        if data is not None:
            if _looks_like_json_schema(data):
                raise ValueError(
                    "Model returned a JSON Schema definition instead of instance data"
                )
            return data
        try:
            json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc

    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        greedy = _remove_trailing_commas(_escape_raw_newlines_in_strings(match.group(0)))
        data = _try_load(greedy)
        if data is not None:
            if _looks_like_json_schema(data):
                raise ValueError(
                    "Model returned a JSON Schema definition instead of instance data"
                )
            return data

    raise ValueError(
        f"No valid JSON object found in model response"
        + (f" ({last_error})" if last_error else "")
    )


def parse_model(schema: type[T], payload: dict[str, Any] | str) -> T:
    if isinstance(payload, str):
        payload = extract_json_object(payload)
    if _looks_like_json_schema(payload):
        raise ValueError(
            f"Model returned a JSON Schema instead of {schema.__name__} instance data"
        )
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Failed to validate {schema.__name__}: {exc}") from exc
