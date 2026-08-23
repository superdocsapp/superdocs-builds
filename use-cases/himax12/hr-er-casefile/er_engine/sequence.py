from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

LetterKind = Literal[
    "improvement_plan",
    "absence",
    "invite_to_hearing",
    "outcome",
    "appeal_response",
]

# Order is the process. A letter may only be issued when its prerequisite is done.
PREREQ: dict[LetterKind, str | None] = {
    "improvement_plan": "open_case",
    "absence": "open_case",
    "invite_to_hearing": "meeting_notes",
    "outcome": "hearing_notes",
    "appeal_response": "outcome_letter",
}

MILESTONES = (
    "open_case",
    "meeting_notes",
    "invite_to_hearing",
    "hearing_notes",
    "outcome_letter",
    "appeal_response",
)


@dataclass
class CaseFile:
    case_id: str
    employee_name: str
    employee_id: str
    done: set[str] = field(default_factory=set)
    chronology: list[str] = field(default_factory=list)
    letters: dict[str, str] = field(default_factory=dict)
    meeting_notes: str = ""
    hearing_notes: str = ""
    employee_verbatim: str = ""
    last_refusal: str | None = None

    def open_case(self) -> None:
        self.done.add("open_case")
        self.chronology.append("Case opened.")


def refuse(kind: LetterKind, missing: str) -> str:
    return (
        f"Refused to issue {kind.replace('_', ' ')}: the process requires "
        f"'{missing.replace('_', ' ')}' first. SuperDocs will not skip a statutory-style step. "
        f"Complete that milestone, then retry."
    )


def can_issue(case: CaseFile, kind: LetterKind) -> tuple[bool, str | None]:
    need = PREREQ[kind]
    if need and need not in case.done:
        return False, refuse(kind, need)
    return True, None


def record_meeting_notes(case: CaseFile, notes: str, employee_verbatim: str) -> None:
    if "open_case" not in case.done:
        raise ValueError("Refused: open the case before recording meeting notes.")
    case.meeting_notes = notes
    case.employee_verbatim = employee_verbatim
    case.done.add("meeting_notes")
    case.chronology.append("Meeting notes recorded. Employee words stored verbatim.")


def record_hearing_notes(case: CaseFile, notes: str, employee_verbatim: str | None = None) -> None:
    if "invite_to_hearing" not in case.done:
        raise ValueError(refuse("outcome", "invite_to_hearing"))
    case.hearing_notes = notes
    if employee_verbatim:
        case.employee_verbatim = employee_verbatim
    case.done.add("hearing_notes")
    case.chronology.append("Hearing notes recorded.")


def outcome_summary(case: CaseFile) -> str:
    """Employee speech is copied, never rewritten."""
    if not case.employee_verbatim:
        raise ValueError("No employee verbatim on file; cannot draft an outcome summary.")
    return (
        "Summary of the employee's response (verbatim, not paraphrased):\n\n"
        f"\"{case.employee_verbatim}\""
    )
