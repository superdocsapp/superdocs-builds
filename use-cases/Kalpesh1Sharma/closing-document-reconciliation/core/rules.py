from __future__ import annotations

import re
from dataclasses import dataclass

from core.models import Classification, FileRule


@dataclass(frozen=True)
class RuleEvaluation:
    classification: Classification
    explanation: str
    recommended_action: str | None
    requires_human_review: bool


def _normalized_rule_text(rule: FileRule | None) -> str:
    if rule is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        rule.rule_text.casefold(),
    ).strip()


def numeric_tolerance_from_rule(
    rule: FileRule | None,
) -> float | None:
    """
    Derive a numeric tolerance from the actual rule text.

    Supported deterministic patterns in the declared file format:
    - exact / exactly match -> 0
    - difference of up to $250 -> 250
    - difference greater than $500 -> 500
    - escrow must remain enabled unless waived -> exact boolean match (0)

    If no supported threshold can be derived, return None rather than
    inventing a tolerance.
    """

    text = _normalized_rule_text(rule)

    if not text:
        return None

    threshold_match = re.search(
        r"(?:up to|greater than|more than|exceeds?)\s*"
        r"\$?\s*([\d,]+(?:\.\d+)?)",
        text,
    )

    if threshold_match:
        return float(
            threshold_match.group(1).replace(",", "")
        )

    if (
        "exactly match" in text
        or "exact match" in text
        or "match exactly" in text
    ):
        return 0.0

    if (
        "must remain enabled" in text
        and "unless" in text
    ):
        return 0.0

    return None


def rule_supports_correction(
    rule: FileRule | None,
) -> bool:
    """Return True only when the file rule itself describes a cure/review."""

    text = _normalized_rule_text(rule)

    if not text:
        return False

    cure_markers = (
        "requires a revised",
        "requires revised",
        "requires review",
        "requires correction",
        "review and correction",
        "revised closing disclosure",
        "revised disclosure",
        "before funding",
    )

    return any(
        marker in text
        for marker in cure_markers
    )


def rule_supports_middle_initial_omission(
    rule: FileRule | None,
) -> bool:
    text = _normalized_rule_text(rule)

    return (
        "middle initial" in text
        and (
            "may be omitted" in text
            or "can be omitted" in text
            or "may omit" in text
        )
    )


def rule_supports_address_abbreviations(
    rule: FileRule | None,
) -> bool:
    text = _normalized_rule_text(rule)

    return (
        "abbreviation" in text
        and "property" in text
        and "address" in text
        and (
            "do not constitute" in text
            or "does not constitute" in text
            or "not a variance" in text
        )
    )


def evaluate_numeric_tolerance(
    *,
    reference_value: float,
    observed_value: float,
    tolerance: float | None,
    rule: FileRule | None,
    curable_action: str | None = None,
) -> RuleEvaluation:
    """
    Evaluate a numeric difference against an explicit file-derived rule.

    A variance is classified only when both the rule and a supported
    tolerance derived from that rule are available. Exceeding a tolerance
    is classified as curable only when the same rule also supports a
    corrective/review action.
    """

    difference = abs(observed_value - reference_value)

    if rule is None:
        return RuleEvaluation(
            classification=Classification.UNCLASSIFIED,
            explanation=(
                f"A difference of {difference:g} was detected, but no "
                "applicable file rule was supplied."
            ),
            recommended_action=(
                "Human review required because the file does not provide "
                "enough rule evidence to classify this variance."
            ),
            requires_human_review=True,
        )

    if tolerance is None:
        return RuleEvaluation(
            classification=Classification.UNCLASSIFIED,
            explanation=(
                f"A difference of {difference:g} was detected. "
                f"Rule {rule.rule_id} is present, but no supported numeric "
                "tolerance could be derived from its text."
            ),
            recommended_action=(
                "Human review required because the rule does not provide "
                "a machine-readable tolerance for this variance."
            ),
            requires_human_review=True,
        )

    if difference <= tolerance:
        return RuleEvaluation(
            classification=Classification.TOLERABLE,
            explanation=(
                f"The observed difference is {difference:g}. "
                f"Rule {rule.rule_id} permits a difference up to "
                f"{tolerance:g}, so this variance is within tolerance."
            ),
            recommended_action=None,
            requires_human_review=False,
        )

    if curable_action is None:
        return RuleEvaluation(
            classification=Classification.UNCLASSIFIED,
            explanation=(
                f"The observed difference is {difference:g}. "
                f"Rule {rule.rule_id} permits a difference up to "
                f"{tolerance:g}, so the tolerance is exceeded, but the "
                "rule does not provide enough supported cure language to "
                "classify the variance as curable."
            ),
            recommended_action="Human review required.",
            requires_human_review=True,
        )

    return RuleEvaluation(
        classification=Classification.CURABLE,
        explanation=(
            f"The observed difference is {difference:g}. "
            f"Rule {rule.rule_id} permits a difference up to "
            f"{tolerance:g}; therefore the allowed tolerance is exceeded."
        ),
        recommended_action=curable_action,
        requires_human_review=True,
    )
