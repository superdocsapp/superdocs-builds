from __future__ import annotations

from datetime import date, timedelta

from .models import CorrectiveItem, CorrectivePlan, Violation


_OWNER_BY_CODE_PREFIX = {
    "5-": "Facilities Lead",
    "3-": "Kitchen Manager",
    "6-": "Closing Supervisor",
}


def generate_offline_plan(
    *,
    restaurant: str,
    inspection_date: date,
    health_department: str,
    violations: tuple[Violation, ...] | list[Violation],
) -> CorrectivePlan:
    items = tuple(
        CorrectiveItem(
            code=violation.code,
            finding=violation.description,
            corrective_action=_action_for(violation),
            responsible_party=_owner_for(violation.code),
            completion_target=(inspection_date + timedelta(days=index)).isoformat(),
            evidence=_evidence_for(violation),
        )
        for index, violation in enumerate(violations, start=1)
    )
    return CorrectivePlan(
        restaurant=restaurant,
        inspection_date=inspection_date,
        health_department=health_department,
        items=items,
    )


def _owner_for(code: str) -> str:
    for prefix, owner in _OWNER_BY_CODE_PREFIX.items():
        if code.startswith(prefix):
            return owner
    return "General Manager"


def _action_for(violation: Violation) -> str:
    text = f"{violation.description} {violation.location or ''}".lower()
    location = violation.location or "the cited area"

    if "handwashing" in text or "hot water" in text:
        return (
            f"Restore hot water at {location} to at least 100 F, verify the faucet "
            "temperature at opening and mid-shift, and keep a signed sink-temperature "
            "log at the station."
        )
    if "hot-holding" in text or "hot holding" in text or "steam well" in text:
        return (
            f"Discard food held below 135 F at {location}, recalibrate the holding "
            "equipment before service, and record line temperatures every two hours "
            "until seven consecutive compliant readings are logged."
        )
    if "grease" in text or "debris" in text or "fryer" in text or "clean" in text:
        return (
            f"Deep clean beneath and behind {location}, add that floor area to the "
            "nightly closing checklist, and require dated photos after each closing "
            "shift for one week."
        )
    return (
        f"Assign the cited condition at {location} to the responsible manager, correct "
        "the physical condition described in the finding, document the completed work, "
        "and verify it during the next pre-service inspection."
    )


def _evidence_for(violation: Violation) -> str:
    text = f"{violation.description} {violation.location or ''}".lower()
    if "handwashing" in text or "hot water" in text:
        return "Repair invoice and sink-temperature log"
    if "hot-holding" in text or "hot holding" in text or "steam well" in text:
        return "Discard log, equipment calibration record, and hot-holding log"
    if "grease" in text or "debris" in text or "fryer" in text:
        return "Updated closing checklist and dated cleaning photos"
    return "Manager sign-off and dated corrective-action photo"
