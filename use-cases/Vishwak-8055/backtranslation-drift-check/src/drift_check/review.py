"""Human review workflow.

A finding's ``review_status`` only ever changes through this module, and
only ever through an explicit call naming a reviewer. There is no code path
anywhere in the pipeline that sets a finding to ``APPROVED`` on its own
initiative — the closest thing is the automatic ``APPROVED`` status on a
PASS finding (drift_engine._pass_finding), which reflects that there was
never a correction to approve in the first place, not that a correction was
silently accepted.
"""

from __future__ import annotations

from drift_check.models import DriftFinding, ReviewDecision, ReviewStatus, utc_now_iso


class ReviewError(ValueError):
    pass


def _require_pending(finding: DriftFinding) -> None:
    if finding.review_status in (ReviewStatus.APPROVED, ReviewStatus.REJECTED, ReviewStatus.EDITED):
        raise ReviewError(
            f"finding {finding.id} already has a recorded decision ({finding.review_status.value}); "
            "re-review is not supported in this workflow"
        )


def approve(finding: DriftFinding, *, reviewer: str, note: str | None = None) -> ReviewDecision:
    _require_pending(finding)
    finding.review_status = ReviewStatus.APPROVED
    return ReviewDecision(
        finding_id=finding.id, decision="approved", reviewer=reviewer, decided_at=utc_now_iso(), note=note
    )


def reject(finding: DriftFinding, *, reviewer: str, note: str | None = None) -> ReviewDecision:
    _require_pending(finding)
    finding.review_status = ReviewStatus.REJECTED
    return ReviewDecision(
        finding_id=finding.id, decision="rejected", reviewer=reviewer, decided_at=utc_now_iso(), note=note
    )


def edit(finding: DriftFinding, *, reviewer: str, edited_text: str, note: str | None = None) -> ReviewDecision:
    """Record a human-edited replacement for the translation.

    Deliberately does not mutate ``finding.proposed_correction`` (it is
    frozen, and for a good reason beyond immutability-for-its-own-sake): the
    finding should keep recording what the *system* originally proposed, so
    a later audit can see both what was suggested and what the reviewer
    actually decided to use — that comparison is exactly what an auditor
    reviewing this workflow would want to see. The reviewer's final text
    lives on the ``ReviewDecision`` returned here.
    """
    _require_pending(finding)
    if not edited_text.strip():
        raise ReviewError("edited_text must not be empty")
    finding.review_status = ReviewStatus.EDITED
    return ReviewDecision(
        finding_id=finding.id,
        decision="edited",
        reviewer=reviewer,
        decided_at=utc_now_iso(),
        edited_text=edited_text,
        note=note,
    )


def approved_corrections(findings: list[DriftFinding]) -> list[DriftFinding]:
    """Findings whose correction has been explicitly approved or edited — the only
    findings it would ever be safe to apply back into a translation file."""
    approved_or_edited = (ReviewStatus.APPROVED, ReviewStatus.EDITED)
    return [f for f in findings if f.review_status in approved_or_edited and f.proposed_correction]


def outstanding_review(findings: list[DriftFinding]) -> list[DriftFinding]:
    return [f for f in findings if f.review_status in (ReviewStatus.PENDING_REVIEW, ReviewStatus.REVIEW_REQUIRED)]
