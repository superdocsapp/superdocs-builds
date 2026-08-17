from dataclasses import dataclass

from core.models import Classification, FileRule


@dataclass(frozen=True)
class RuleEvaluation:
    classification: Classification
    explanation: str
    recommended_action: str | None
    requires_human_review: bool


def evaluate_numeric_tolerance(
    *,
    reference_value: float,
    observed_value: float,
    tolerance: float,
    rule: FileRule | None,
    curable_action: str | None = None,
) -> RuleEvaluation:
    """
    Evaluate a numeric difference against an explicit file-derived rule.

    The tolerance is supplied by structured rule data. This function does
    not invent mortgage/compliance rules.
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