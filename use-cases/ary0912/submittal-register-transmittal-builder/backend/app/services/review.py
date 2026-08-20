from datetime import datetime

from sqlalchemy.orm import Session

from app.models.finding import Finding
from app.models.submittal import Submittal


VALID_DECISIONS = {
    "APPROVE",
    "REJECT",
    "REQUEST_CLARIFICATION",
}


def review_finding(
    db: Session,
    finding_id: str,
    reviewer: str,
    decision: str,
    comment: str | None = None,
) -> Finding:

    if decision not in VALID_DECISIONS:
        raise ValueError(
            f"Unsupported decision: {decision}"
        )

    finding = (
        db.query(Finding)
        .filter(Finding.id == finding_id)
        .first()
    )

    if finding is None:
        raise ValueError(
            f"Finding {finding_id} was not found."
        )

    if finding.status != "PENDING_REVIEW":
        raise ValueError(
            f"Finding {finding_id} has already been reviewed."
        )

    status_map = {
        "APPROVE": "APPROVED",
        "REJECT": "REJECTED",
        "REQUEST_CLARIFICATION": (
            "CLARIFICATION_REQUESTED"
        ),
    }

    finding.status = status_map[decision]
    finding.reviewer = reviewer
    finding.reviewer_comment = comment
    finding.reviewed_at = datetime.utcnow()

    db.commit()
    db.refresh(finding)

    return finding