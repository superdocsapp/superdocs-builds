"""Boundary validation for researcher-supplied inputs."""

from __future__ import annotations

import re

from .models import PaperInputs


class InputValidationError(ValueError):
    """Raised when one or more input fields are invalid."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("Invalid paper inputs")
        self.errors = errors


_MAX_LENGTHS = {
    "research_question": 2_000,
    "methodology": 12_000,
    "dataset_description": 12_000,
    "journal_template": 20_000,
}


def _clean_prose(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def validate_inputs(inputs: PaperInputs) -> PaperInputs:
    """Validate inputs while preserving missing optional evidence as empty text."""

    values = {
        "research_question": _clean_prose(inputs.research_question),
        "methodology": _clean_prose(inputs.methodology),
        "dataset_description": _clean_prose(inputs.dataset_description),
        "journal_template": inputs.journal_template.strip(),
    }
    errors: dict[str, str] = {}

    if not values["research_question"]:
        errors["research_question"] = "A research question is required."
    if not values["journal_template"]:
        errors["journal_template"] = (
            "Journal template information with an explicit section structure is required."
        )

    for field, maximum in _MAX_LENGTHS.items():
        if len(values[field]) > maximum:
            errors[field] = f"Must contain no more than {maximum} characters."

    if errors:
        raise InputValidationError(errors)

    return PaperInputs(**values)
