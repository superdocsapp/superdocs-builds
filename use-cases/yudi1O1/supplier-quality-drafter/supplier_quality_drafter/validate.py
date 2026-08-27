"""Validation gate: the drafter must never invent a number the engineer didn't supply.

`validate_request` is the single choke point every draft passes through before
any network call is made. It returns a `ValidationResult` that is either clean
(safe to draft) or carries a list of `Finding`s that must be resolved by the
engineer first — the CLI refuses to draft while blocking findings exist.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import DraftRequest


@dataclass
class Finding:
    severity: str  # "blocking" | "warning"
    location: str  # e.g. "failure_mode FM-01" or "action AC-03"
    message: str


@dataclass
class ValidationResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def ok_to_draft(self) -> bool:
        return len(self.blocking) == 0


def validate_request(req: DraftRequest) -> ValidationResult:
    result = ValidationResult()

    if req.document_type in ("fmea", "combined"):
        _validate_fmea(req, result)

    if req.document_type in ("ppap", "combined") and req.ppap is not None:
        _validate_ppap(req, result)

    if req.document_type in ("8d", "combined") and req.eightd is not None:
        _validate_8d(req, result)

    return result


def _validate_fmea(req: DraftRequest, result: ValidationResult) -> None:
    if not req.failure_modes:
        result.findings.append(
            Finding("blocking", "failure_modes", "No failure modes supplied — an FMEA needs at least one row.")
        )
        return

    seen_ids: set[str] = set()
    for fm in req.failure_modes:
        loc = f"failure_mode {fm.id}"
        if fm.id in seen_ids:
            result.findings.append(Finding("blocking", loc, f"Duplicate failure mode id '{fm.id}'."))
        seen_ids.add(fm.id)

        missing = fm.missing_fields()
        for field_name in missing:
            result.findings.append(
                Finding(
                    "blocking",
                    loc,
                    f"{field_name} was not supplied. Ask the engineer for a 1-10 {field_name} rating "
                    f"instead of drafting a number for it.",
                )
            )
        for field_name, value in (("severity", fm.severity), ("occurrence", fm.occurrence), ("detection", fm.detection)):
            if value is not None and not (1 <= value <= 10):
                result.findings.append(
                    Finding("blocking", loc, f"{field_name}={value} is out of the 1-10 AIAG-VDA range.")
                )

    # Every action must trace to a named, existing failure mode.
    for action in req.actions:
        loc = f"action {action.id}"
        if not action.failure_mode_id:
            result.findings.append(Finding("blocking", loc, "Action has no failure_mode_id — it must trace to a failure mode."))
        elif action.failure_mode_id not in seen_ids:
            result.findings.append(
                Finding(
                    "blocking",
                    loc,
                    f"Action references failure_mode_id '{action.failure_mode_id}', which does not exist "
                    f"among the supplied failure modes.",
                )
            )

    # A failure mode with no linked action isn't invalid, but it's worth flagging —
    # especially for high-RPN rows.
    linked_fm_ids = {a.failure_mode_id for a in req.actions}
    for fm in req.failure_modes:
        rpn = fm.rpn()
        if fm.id not in linked_fm_ids and rpn is not None and rpn >= 100:
            result.findings.append(
                Finding(
                    "warning",
                    f"failure_mode {fm.id}",
                    f"RPN={rpn} (>=100) has no recommended action linked to it.",
                )
            )


def _validate_ppap(req: DraftRequest, result: ValidationResult) -> None:
    ppap = req.ppap
    assert ppap is not None
    if ppap.submission_level is None:
        result.findings.append(
            Finding("blocking", "ppap.submission_level", "PPAP submission level (1-5) was not supplied.")
        )
    elif not (1 <= ppap.submission_level <= 5):
        result.findings.append(
            Finding("blocking", "ppap.submission_level", f"submission_level={ppap.submission_level} is out of range 1-5.")
        )
    if not ppap.reason_for_submission.strip():
        result.findings.append(
            Finding("blocking", "ppap.reason_for_submission", "Reason for submission was not supplied.")
        )


def _validate_8d(req: DraftRequest, result: ValidationResult) -> None:
    eightd = req.eightd
    assert eightd is not None
    required = {
        "d2_problem_description": eightd.d2_problem_description,
        "d4_root_cause": eightd.d4_root_cause,
        "d5_permanent_corrective_actions": eightd.d5_permanent_corrective_actions,
    }
    for field_name, value in required.items():
        if not value.strip():
            result.findings.append(
                Finding("blocking", f"8d.{field_name}", f"{field_name} was not supplied and is required to draft an 8D.")
            )
