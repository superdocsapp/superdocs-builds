from dataclasses import dataclass

from schema import HandoffEnvelope, ReviewState, validate_envelope


@dataclass(frozen=True)
class ActionDiff:
    document_id: str
    issued_by: str
    receiver: str
    action: str
    changed_sections: frozenset[str]


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str


def validate_action(raw_envelope: dict | HandoffEnvelope, action: ActionDiff) -> ValidationResult:
    try:
        envelope = (
            validate_envelope(raw_envelope)
            if isinstance(raw_envelope, dict)
            else raw_envelope
        )
    except ValueError as error:
        return ValidationResult(False, f"invalid envelope: {error}")

    if action.document_id != envelope.document_id:
        return ValidationResult(False, "action document_id does not match envelope")

    if action.receiver != envelope.assigned_to:
        return ValidationResult(False, "action receiver does not match envelope assignment")

    if envelope.review_state in {ReviewState.APPROVED, ReviewState.REJECTED}:
        return ValidationResult(
            False,
            f"document review_state {envelope.review_state.value} does not permit mutation",
        )

    target_sections = set(envelope.scope.target_sections)
    forbidden_sections = set(envelope.restrictions.forbidden_sections)
    outside_scope = action.changed_sections - target_sections
    if outside_scope:
        return ValidationResult(
            False,
            "action changed sections outside scope: " +
            ", ".join(sorted(outside_scope)),
        )

    forbidden_changes = action.changed_sections & forbidden_sections
    if forbidden_changes:
        return ValidationResult(
            False,
            "action changed forbidden sections: " +
            ", ".join(sorted(forbidden_changes)),
        )

    if action.action in envelope.restrictions.forbidden_actions:
        return ValidationResult(False, f"action is forbidden: {action.action}")

    if action.action != envelope.scope.action:
        return ValidationResult(
            False,
            f"action does not match scope: expected {envelope.scope.action!r}",
        )

    return ValidationResult(True, "action respected envelope scope and restrictions")
