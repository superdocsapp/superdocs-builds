from dataclasses import dataclass

from docrelay.domain.enums import EffectOutcome


class IllegalEffectTransition(ValueError):
    """Raised when an effect outcome would erase uncertainty or invent success."""


@dataclass(frozen=True, slots=True)
class EffectTransition:
    from_outcome: EffectOutcome
    to_outcome: EffectOutcome
    requires_reconciliation: bool


def require_effect_transition(
    from_outcome: EffectOutcome,
    to_outcome: EffectOutcome,
    *,
    definitive_non_occurrence: bool = False,
    reconciliation_evidence: bool = False,
) -> EffectTransition:
    if from_outcome is EffectOutcome.SUCCEEDED:
        raise IllegalEffectTransition("SUCCEEDED is terminal")

    if from_outcome is EffectOutcome.NOT_STARTED and to_outcome is EffectOutcome.STARTED:
        return EffectTransition(from_outcome, to_outcome, requires_reconciliation=False)

    if from_outcome is EffectOutcome.STARTED and to_outcome in {
        EffectOutcome.SUCCEEDED,
        EffectOutcome.UNKNOWN,
    }:
        return EffectTransition(from_outcome, to_outcome, requires_reconciliation=False)

    if (
        from_outcome is EffectOutcome.STARTED
        and to_outcome is EffectOutcome.NOT_STARTED
        and definitive_non_occurrence
    ):
        return EffectTransition(from_outcome, to_outcome, requires_reconciliation=False)

    if (
        from_outcome is EffectOutcome.UNKNOWN
        and to_outcome in {EffectOutcome.SUCCEEDED, EffectOutcome.NOT_STARTED}
        and reconciliation_evidence
    ):
        return EffectTransition(from_outcome, to_outcome, requires_reconciliation=True)

    raise IllegalEffectTransition(
        f"illegal external-effect transition: {from_outcome} -> {to_outcome}"
    )
