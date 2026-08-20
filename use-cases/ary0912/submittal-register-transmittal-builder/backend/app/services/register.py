from datetime import date, datetime
import re
from typing import Iterable, Mapping

from sqlalchemy.orm import Session

from app.models.finding import Finding
from app.models.submittal import Submittal


REGISTER_STATUSES = {
    "NOT_RECEIVED",
    "RECEIVED",
    "UNDER_REVIEW",
    "REVIEWED",
    "OVERDUE",
}

_REGISTER_NUMBER_PATTERN = re.compile(r"^SUB-(\d+)$")


def _next_register_number(
    db: Session,
) -> str:
    highest = 0

    for number, in db.query(Submittal.number).all():
        match = _REGISTER_NUMBER_PATTERN.match(number or "")
        if match:
            highest = max(highest, int(match.group(1)))

    return f"SUB-{highest + 1:03d}"


def _requirement_match(
    submittal: Submittal,
    requirement: Mapping[str, object],
    project_id: str,
) -> bool:
    return (
        submittal.project_id == project_id
        and submittal.specification_section.strip().casefold()
        == str(requirement["specification_section"]).strip().casefold()
        and submittal.title.strip().casefold()
        == str(requirement["title"]).strip().casefold()
    )


def _apply_requirement(
    submittal: Submittal,
    requirement: Mapping[str, object],
) -> Submittal:
    submittal.title = str(requirement["title"])
    submittal.description = (
        str(requirement["description"])
        if requirement.get("description") is not None
        else None
    )
    submittal.specification_section = str(
        requirement["specification_section"]
    )
    submittal.required_by = (
        str(requirement["required_by"])
        if requirement.get("required_by") is not None
        else None
    )
    submittal.required_form = (
        str(requirement["required_form"])
        if requirement.get("required_form") is not None
        else None
    )
    submittal.source_evidence = (
        str(requirement["source_evidence"])
        if requirement.get("source_evidence") is not None
        else None
    )
    submittal.specification_revision = (
        str(requirement["specification_revision"])
        if requirement.get("specification_revision") is not None
        else None
    )
    submittal.due_date = requirement.get("due_date")
    return submittal


def create_register_item(
    db: Session,
    project_id: str,
    requirement: Mapping[str, object],
) -> Submittal:
    """Create one normalized, evidence-backed register row."""

    required_fields = (
        "title",
        "specification_section",
        "source_evidence",
    )
    missing = [
        field
        for field in required_fields
        if field not in requirement
    ]
    if missing:
        raise ValueError(
            "Register requirement is missing: "
            + ", ".join(missing)
        )

    if not str(requirement["title"]).strip():
        raise ValueError("Register requirement title cannot be empty.")
    if not str(requirement["specification_section"]).strip():
        raise ValueError(
            "Register requirement specification_section cannot be empty."
        )
    if not str(requirement["source_evidence"]).strip():
        raise ValueError(
            "Register requirement source_evidence cannot be empty."
        )

    submittal = Submittal(
        project_id=project_id,
        number=_next_register_number(db),
        title=str(requirement["title"]),
        status="PENDING",
        register_status="NOT_RECEIVED",
    )
    _apply_requirement(submittal, requirement)
    db.add(submittal)
    db.flush()
    return submittal


def update_register_item(
    db: Session,
    submittal: Submittal,
    requirement: Mapping[str, object],
) -> Submittal:
    """Update an existing requirement while preserving its identity."""

    _apply_requirement(submittal, requirement)
    db.flush()
    return submittal


def generate_register(
    db: Session,
    project_id: str,
    requirements: Iterable[Mapping[str, object]],
) -> list[Submittal]:
    """Upsert normalized specification requirements into the register.

    Matching uses project_id + specification_section + title because the
    current input contract has no stable source requirement identifier.
    A revision therefore updates the existing row rather than creating a
    duplicate; a genuinely new title/section pair gets a new number.
    """

    result: list[Submittal] = []
    existing = (
        db.query(Submittal)
        .filter(Submittal.project_id == project_id)
        .all()
    )

    for requirement in requirements:
        match = next(
            (
                submittal
                for submittal in existing
                if _requirement_match(
                    submittal,
                    requirement,
                    project_id,
                )
            ),
            None,
        )

        if match is None:
            match = create_register_item(
                db,
                project_id,
                requirement,
            )
            existing.append(match)
        else:
            update_register_item(
                db,
                match,
                requirement,
            )

        result.append(match)

    db.commit()
    for submittal in result:
        db.refresh(submittal)
    return result


def get_register(
    db: Session,
    project_id: str,
) -> list[Submittal]:
    return (
        db.query(Submittal)
        .filter(Submittal.project_id == project_id)
        .order_by(Submittal.number.asc())
        .all()
    )


def update_register_status(
    db: Session,
    submittal: Submittal,
    register_status: str,
) -> Submittal:
    if register_status not in REGISTER_STATUSES:
        raise ValueError(
            f"Unsupported register status: {register_status}"
        )

    if register_status == "REVIEWED":
        findings = (
            db.query(Finding)
            .filter(Finding.submittal_id == submittal.id)
            .all()
        )
        unresolved = [
            f
            for f in findings
            if f.status in {"PENDING_REVIEW", "CLARIFICATION_REQUESTED"}
        ]
        if unresolved:
            raise ValueError(
                "Cannot mark submittal as REVIEWED while findings remain unresolved."
            )

    submittal.register_status = register_status
    submittal.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(submittal)
    return submittal


def get_overdue_submittals(
    db: Session,
    project_id: str,
    today: date,
) -> list[Submittal]:
    """Return unresolved register rows whose due date has passed."""

    return (
        db.query(Submittal)
        .filter(
            Submittal.project_id == project_id,
            Submittal.due_date.is_not(None),
            Submittal.due_date < today,
            Submittal.register_status != "REVIEWED",
        )
        .order_by(Submittal.due_date.asc())
        .all()
    )


def update_submittal_status(
    db: Session,
    submittal_id: str,
) -> Submittal:
    """Recalculate technical status and the separate register status."""

    submittal = (
        db.query(Submittal)
        .filter(Submittal.id == submittal_id)
        .first()
    )

    if submittal is None:
        raise ValueError(
            f"Submittal {submittal_id} was not found."
        )

    findings = (
        db.query(Finding)
        .filter(
            Finding.submittal_id == submittal_id
        )
        .all()
    )

    pending = [
        finding
        for finding in findings
        if finding.status
        in {
            "PENDING_REVIEW",
            "CLARIFICATION_REQUESTED",
        }
    ]

    approved_deviations = [
        finding
        for finding in findings
        if (
            finding.status == "APPROVED"
            and finding.result == "DEVIATION"
        )
    ]

    if not findings:
        submittal.status = "REVIEWED"
    elif pending:
        submittal.status = "PENDING_REVIEW"
    elif approved_deviations:
        submittal.status = "REVIEWED_DEVIATION"
    else:
        submittal.status = "REVIEWED_COMPLIANT"

    if pending:
        submittal.register_status = "UNDER_REVIEW"
    elif findings:
        submittal.register_status = "REVIEWED"

    submittal.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(submittal)
    return submittal
