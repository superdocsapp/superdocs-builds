import pytest

from docrelay.domain.effects import IllegalEffectTransition, require_effect_transition
from docrelay.domain.enums import EffectOutcome


def test_effect_can_record_success_or_uncertainty_after_dispatch() -> None:
    require_effect_transition(EffectOutcome.NOT_STARTED, EffectOutcome.STARTED)
    require_effect_transition(EffectOutcome.STARTED, EffectOutcome.SUCCEEDED)
    require_effect_transition(EffectOutcome.STARTED, EffectOutcome.UNKNOWN)


def test_definitive_provider_rejection_can_record_no_effect() -> None:
    transition = require_effect_transition(
        EffectOutcome.STARTED,
        EffectOutcome.NOT_STARTED,
        definitive_non_occurrence=True,
    )
    assert not transition.requires_reconciliation


def test_unknown_outcome_requires_reconciliation_evidence() -> None:
    with pytest.raises(IllegalEffectTransition):
        require_effect_transition(EffectOutcome.UNKNOWN, EffectOutcome.SUCCEEDED)

    transition = require_effect_transition(
        EffectOutcome.UNKNOWN,
        EffectOutcome.SUCCEEDED,
        reconciliation_evidence=True,
    )
    assert transition.requires_reconciliation


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (EffectOutcome.NOT_STARTED, EffectOutcome.SUCCEEDED),
        (EffectOutcome.UNKNOWN, EffectOutcome.STARTED),
        (EffectOutcome.SUCCEEDED, EffectOutcome.UNKNOWN),
    ],
)
def test_effect_policy_never_invents_or_erases_an_outcome(
    source: EffectOutcome, target: EffectOutcome
) -> None:
    with pytest.raises(IllegalEffectTransition):
        require_effect_transition(source, target)
