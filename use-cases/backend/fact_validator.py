from dataclasses import dataclass
from typing import Any

from backend.fact_model import GameFacts


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: str = "error"


@dataclass
class ValidationResult:
    valid: bool
    issues: list[ValidationIssue]


def _issue(field: str, expected: Any, actual: Any) -> ValidationIssue:
    return ValidationIssue(
        field=field,
        message=f"Expected {expected!r}, got {actual!r}.",
    )


def validate_fact_sheet(facts: GameFacts, generated: dict) -> ValidationResult:
    """Validate every required fact-sheet field against the source facts."""
    expected = {
        "studio": facts.game.studio,
        "release_date": facts.game.release_date,
        "platforms": facts.game.platforms,
        "price": facts.game.price,
        "availability": facts.game.availability,
    }
    issues: list[ValidationIssue] = []
    for field, value in expected.items():
        actual = generated.get(field)
        if field == "platforms":
            if list(actual or []) != list(value):
                issues.append(_issue(field, value, actual))
        elif actual != value:
            issues.append(_issue(field, value, actual))
    return ValidationResult(valid=not issues, issues=issues)


def validate_press_kit(facts: GameFacts, press_kit: dict) -> ValidationResult:
    """Validate factual invariants and source-backed narrative structure."""
    issues = list(validate_fact_sheet(facts, press_kit.get("fact_sheet", {})).issues)

    expected_assets = [
        {
            "filename": a.filename,
            "type": a.type,
            "caption": a.caption,
            "credit": a.credit,
        }
        for a in facts.assets
    ]
    if press_kit.get("asset_index") != expected_assets:
        issues.append(_issue("asset_index", expected_assets, press_kit.get("asset_index")))

    expected_quote = {"text": facts.quote.text, "attribution": facts.quote.attribution}
    if press_kit.get("quote") != expected_quote:
        issues.append(_issue("quote", expected_quote, press_kit.get("quote")))

    for name, source_value in (
        ("history", facts.history),
        ("inspiration", facts.inspiration),
    ):
        actual = press_kit.get("history_and_inspiration", {}).get(name)
        if actual != source_value:
            issues.append(_issue(f"history_and_inspiration.{name}", source_value, actual))

    descriptions = press_kit.get("descriptions", {})
    for length in ("one_line", "one_paragraph", "long_form"):
        if not descriptions.get(length):
            issues.append(ValidationIssue(field=f"descriptions.{length}", message="Description is missing."))
        elif facts.core_description not in descriptions[length]:
            issues.append(
                ValidationIssue(
                    field=f"descriptions.{length}",
                    message="Canonical core description is missing; narrative may have drifted from the source.",
                )
            )

    if list(press_kit.get("features", [])) != list(facts.features):
        issues.append(_issue("features", facts.features, press_kit.get("features")))

    return ValidationResult(valid=not issues, issues=issues)
