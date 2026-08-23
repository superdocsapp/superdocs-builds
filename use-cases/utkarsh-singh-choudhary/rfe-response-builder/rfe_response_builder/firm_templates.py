"""
Firm-level template/phrasing customization.

Every firm using this tool gets the exact same drafting-instruction
phrasing and tone regardless of house style -- one firm might want a
terse, direct tone; another might want a more measured, formal register;
a third might want every response to close with a specific standard
paragraph. This module lets a firm supply a small JSON profile
(`FirmTemplate`) that customizes the instruction sent to the drafting
model, without touching the underlying logic in `rfe.py`'s
`build_response_instruction` (which stays the single source of truth for
what information goes into an instruction -- this module only adjusts
phrasing/tone/closing text around it).

A firm template is entirely optional (`None` is always a valid value,
maps to "use the built-in default phrasing," and every field it does set
is additive -- appended to the instruction, never rewriting or removing
the core facts/warnings `build_response_instruction` already put there
(e.g. "do not invent facts" always stays intact). A firm cannot use this
to weaken the anti-hallucination or human-review guardrails; it can only
adjust tone and add closing boilerplate.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FIRM_TEMPLATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["firm_name"],
    "properties": {
        "firm_name": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "tone_instruction": {"type": "string"},
        "category_addenda": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "closing_paragraph": {"type": "string"},
    },
}


class FirmTemplateValidationError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        message = "firm template file failed validation:\n" + "\n".join(f"  - {p}" for p in problems)
        super().__init__(message)


def _validate(data: Any) -> None:
    try:
        import jsonschema
        validator = jsonschema.Draft202012Validator(FIRM_TEMPLATE_SCHEMA)
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        if errors:
            problems = [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]
            raise FirmTemplateValidationError(problems)
    except ImportError:
        # Same dependency-light fallback pattern as schemas.py -- never a
        # hard requirement just to load a firm template.
        if not isinstance(data, dict) or not isinstance(data.get("firm_name"), str) or not data["firm_name"].strip():
            raise FirmTemplateValidationError(["firm_name: required non-empty string"])


@dataclass
class FirmTemplate:
    firm_name: str
    tone_instruction: str = ""
    category_addenda: dict[str, str] = field(default_factory=dict)  # RFECategory value -> extra instruction text
    closing_paragraph: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FirmTemplate":
        _validate(data)
        return cls(
            firm_name=data["firm_name"],
            tone_instruction=data.get("tone_instruction", ""),
            category_addenda=data.get("category_addenda", {}),
            closing_paragraph=data.get("closing_paragraph", ""),
        )


def load_firm_template(path: Path) -> FirmTemplate:
    """Loads and validates a firm template JSON file. Raises
    `FirmTemplateValidationError` (a `ValueError` subclass, so it's
    already caught by the same handlers that catch `SchemaValidationError`
    for petition/evidence uploads) with a readable, per-field problem
    list on malformed input."""
    raw = json.loads(path.read_text())
    return FirmTemplate.from_dict(raw)


def apply_firm_customization(instruction: str, firm_template: "FirmTemplate | None", category_value: str) -> str:
    """Appends the firm's tone instruction, any category-specific
    addendum, and closing paragraph to an already-built instruction (from
    `rfe.build_response_instruction`). Additive only -- never removes or
    rewrites any part of the original instruction, so the anti-
    hallucination and "do not invent facts" guardrails baked into
    `build_response_instruction` are always intact regardless of what a
    firm template says. `firm_template=None` returns `instruction`
    unchanged."""
    if firm_template is None:
        return instruction

    parts = [instruction]
    if firm_template.tone_instruction:
        parts.append(f"\n\nHouse style for {firm_template.firm_name}: {firm_template.tone_instruction}")
    addendum = firm_template.category_addenda.get(category_value)
    if addendum:
        parts.append(f"\n\nAdditional firm guidance for this filing type: {addendum}")
    if firm_template.closing_paragraph:
        parts.append(f"\n\nClose this section with the following standard paragraph, verbatim: "
                      f"\"{firm_template.closing_paragraph}\"")
    return "".join(parts)
