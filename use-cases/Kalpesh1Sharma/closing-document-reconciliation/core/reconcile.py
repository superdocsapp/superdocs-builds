from __future__ import annotations

import math
from collections.abc import Callable

from core.models import (
    Classification,
    DocumentType,
    FieldObservation,
    FileRule,
    FindingStatus,
    ReconciliationFinding,
)
from core.rules import evaluate_numeric_tolerance


def _find_reference(
    observations: list[FieldObservation],
    reference_document: DocumentType,
) -> FieldObservation | None:
    for observation in observations:
        if observation.document_type == reference_document:
            return observation

    return None


def reconcile_numeric_field(
    *,
    field_name: str,
    observations: list[FieldObservation],
    reference_document: DocumentType,
    tolerance: float | None = None,
    applicable_rule: FileRule | None = None,
    curable_action: str | None = None,
) -> ReconciliationFinding:
    """Compare numeric values without inferring missing evidence or rules."""

    reference = _find_reference(
        observations,
        reference_document,
    )

    if reference is None or reference.value is None:
        return ReconciliationFinding(
            field_name=field_name,
            status=FindingStatus.INSUFFICIENT_EVIDENCE,
            classification=Classification.UNCLASSIFIED,
            observations=observations,
            applicable_rule=applicable_rule,
            explanation=(
                f"The reference value for '{field_name}' was not found "
                f"in {reference_document.value}."
            ),
            recommended_action=(
                "Human review required because the reference value "
                "is missing."
            ),
            requires_human_review=True,
        )

    valid_observations = [
        observation
        for observation in observations
        if observation.value is not None
    ]

    if len(valid_observations) < 2:
        return ReconciliationFinding(
            field_name=field_name,
            status=FindingStatus.INSUFFICIENT_EVIDENCE,
            classification=Classification.UNCLASSIFIED,
            observations=observations,
            applicable_rule=applicable_rule,
            explanation=(
                f"Only one supported value was available for "
                f"'{field_name}', so reconciliation is not possible."
            ),
            recommended_action="Human review required.",
            requires_human_review=True,
        )

    reference_value = float(reference.value)
    differences: list[tuple[FieldObservation, float]] = []

    for observation in valid_observations:
        if observation is reference:
            continue

        observed_value = float(observation.value)
        difference = abs(observed_value - reference_value)

        if not math.isclose(
            observed_value,
            reference_value,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            differences.append(
                (observation, difference)
            )

    if not differences:
        return ReconciliationFinding(
            field_name=field_name,
            status=FindingStatus.MATCH,
            classification=Classification.NOT_APPLICABLE,
            observations=observations,
            applicable_rule=applicable_rule,
            explanation=(
                f"All supported values for '{field_name}' match "
                f"the reference value from {reference.filename}."
            ),
            recommended_action=None,
            requires_human_review=False,
        )

    largest_difference = max(
        difference
        for _, difference in differences
    )

    evaluation = evaluate_numeric_tolerance(
        reference_value=reference_value,
        observed_value=reference_value + largest_difference,
        tolerance=tolerance,
        rule=applicable_rule,
        curable_action=curable_action,
    )

    differing_files = ", ".join(
        observation.filename
        for observation, _ in differences
    )

    return ReconciliationFinding(
        field_name=field_name,
        status=FindingStatus.VARIANCE,
        classification=evaluation.classification,
        observations=observations,
        applicable_rule=applicable_rule,
        explanation=(
            f"{evaluation.explanation} "
            f"Different value(s) were found in: {differing_files}."
        ),
        recommended_action=evaluation.recommended_action,
        requires_human_review=evaluation.requires_human_review,
    )


def reconcile_text_field(
    *,
    field_name: str,
    observations: list[FieldObservation],
    reference_document: DocumentType,
    comparator: Callable[[str, str], bool],
    applicable_rule: FileRule | None = None,
) -> ReconciliationFinding:
    """Reconcile textual fields using an explicitly selected comparator."""

    reference = _find_reference(
        observations,
        reference_document,
    )

    if reference is None or reference.value is None:
        return ReconciliationFinding(
            field_name=field_name,
            status=FindingStatus.INSUFFICIENT_EVIDENCE,
            classification=Classification.UNCLASSIFIED,
            observations=observations,
            applicable_rule=applicable_rule,
            explanation=(
                f"The reference value for '{field_name}' was not found "
                f"in {reference_document.value}."
            ),
            recommended_action="Human review required.",
            requires_human_review=True,
        )

    supported = [
        observation
        for observation in observations
        if observation.value is not None
    ]

    if len(supported) < 2:
        return ReconciliationFinding(
            field_name=field_name,
            status=FindingStatus.INSUFFICIENT_EVIDENCE,
            classification=Classification.UNCLASSIFIED,
            observations=observations,
            applicable_rule=applicable_rule,
            explanation=(
                f"Insufficient supported values were available for "
                f"'{field_name}'."
            ),
            recommended_action="Human review required.",
            requires_human_review=True,
        )

    reference_value = str(reference.value)
    mismatches = []

    for observation in supported:
        if observation is reference:
            continue

        if not comparator(
            reference_value,
            str(observation.value),
        ):
            mismatches.append(observation)

    if not mismatches:
        rule_text = ""

        if applicable_rule:
            rule_text = (
                f" Permitted normalization is supported by "
                f"Rule {applicable_rule.rule_id}."
            )

        return ReconciliationFinding(
            field_name=field_name,
            status=FindingStatus.MATCH,
            classification=Classification.NOT_APPLICABLE,
            observations=observations,
            applicable_rule=applicable_rule,
            explanation=(
                f"All supported values for '{field_name}' are "
                f"equivalent after permitted normalization."
                f"{rule_text}"
            ),
            recommended_action=None,
            requires_human_review=False,
        )

    filenames = ", ".join(
        item.filename
        for item in mismatches
    )

    return ReconciliationFinding(
        field_name=field_name,
        status=FindingStatus.VARIANCE,
        classification=Classification.UNCLASSIFIED,
        observations=observations,
        applicable_rule=applicable_rule,
        explanation=(
            f"One or more values for '{field_name}' are not "
            f"equivalent to the reference value. "
            f"Different value(s) found in: {filenames}."
        ),
        recommended_action="Human review required.",
        requires_human_review=True,
    )
