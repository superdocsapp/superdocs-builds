from __future__ import annotations

from dataclasses import dataclass

from .html_units import changed_unit_ids, extract_units
from .models import CorpusCase, EvaluationScore, LabelScope, UnitDiff


@dataclass(frozen=True)
class _ScopeScore:
    scope: LabelScope
    coverage: float
    collateral: float
    loss: float
    changed_expected: set[str]
    missing_expected: set[str]
    incorrect_expected: set[str]
    changed_protected: set[str]
    unexpected_added: set[str]


def _score_scope(
    scope: LabelScope,
    changed: set[str],
    added: set[str],
    after_units: dict[str, str],
) -> _ScopeScore:
    targeted_changes = scope.expected_change_ids & changed
    incorrect_expected = {
        chunk_id
        for chunk_id in targeted_changes
        if not all(
            fragment in after_units.get(chunk_id, "")
            for fragment in scope.required_after_fragments.get(chunk_id, [])
        )
        or any(
            fragment in after_units.get(chunk_id, "")
            for fragment in scope.forbidden_after_fragments.get(chunk_id, [])
        )
    }
    changed_expected = targeted_changes - incorrect_expected
    missing_expected = scope.expected_change_ids - targeted_changes
    changed_protected = scope.protected_ids & changed
    unexpected_added = added - scope.expected_change_ids

    coverage = len(changed_expected) / len(scope.expected_change_ids)
    collateral_denominator = len(scope.protected_ids) + len(unexpected_added)
    collateral = (
        (len(changed_protected) + len(unexpected_added)) / collateral_denominator
        if collateral_denominator
        else 0.0
    )
    loss = (1.0 - coverage) + collateral
    return _ScopeScore(
        scope=scope,
        coverage=coverage,
        collateral=collateral,
        loss=loss,
        changed_expected=changed_expected,
        missing_expected=missing_expected,
        incorrect_expected=incorrect_expected,
        changed_protected=changed_protected,
        unexpected_added=unexpected_added,
    )


def score_edit(case: CorpusCase, before_html: str, after_html: str) -> EvaluationScore:
    """Score an edit against every acceptable label scope and keep the best match.

    Choosing the best documented scope prevents legitimately ambiguous instructions from
    being penalised for selecting one of several human-approved interpretations.
    """

    changed, added = changed_unit_ids(before_html, after_html)
    after_units = extract_units(after_html)
    candidates = [
        _score_scope(scope, changed, added, after_units) for scope in case.acceptable_scopes
    ]
    best = min(candidates, key=lambda item: (item.loss, item.collateral, -item.coverage))

    before_units = extract_units(before_html)
    relevant_ids = (
        best.changed_expected
        | best.missing_expected
        | best.incorrect_expected
        | best.changed_protected
        | best.unexpected_added
    )
    diffs: list[UnitDiff] = []
    for chunk_id in sorted(relevant_ids):
        if chunk_id in best.incorrect_expected:
            classification = "incorrect_intended_change"
        elif chunk_id in best.changed_expected:
            classification = "intended_change"
        elif chunk_id in best.missing_expected:
            classification = "missed_intended_change"
        elif chunk_id in best.unexpected_added:
            classification = "unexpected_addition"
        else:
            classification = "collateral_change"
        diffs.append(
            UnitDiff(
                chunk_id=chunk_id,
                classification=classification,
                before_html=before_units.get(chunk_id),
                after_html=after_units.get(chunk_id),
            )
        )

    return EvaluationScore(
        case_id=case.case_id,
        matched_scope_id=best.scope.scope_id,
        intended_change_coverage=round(best.coverage, 6),
        collateral_damage_rate=round(best.collateral, 6),
        precision_loss=round(best.loss, 6),
        changed_expected_ids=sorted(best.changed_expected),
        missing_expected_ids=sorted(best.missing_expected),
        incorrect_expected_ids=sorted(best.incorrect_expected),
        changed_protected_ids=sorted(best.changed_protected),
        unexpected_added_ids=sorted(best.unexpected_added),
        unit_diffs=diffs,
    )
