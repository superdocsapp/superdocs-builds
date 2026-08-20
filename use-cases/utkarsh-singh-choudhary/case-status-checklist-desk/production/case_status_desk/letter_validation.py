"""
Automated validation of a generated letter draft against the case's true
current state -- catches drift between what the AI wrote and what the
case record actually says, before a human approver ever sees it.

This does NOT replace human review (the approval gate stays mandatory).
It's a second, cheap, deterministic check that runs first and can flag
or block obviously wrong drafts -- e.g. a received document still listed
as outstanding, an outstanding document silently dropped, or a form_type
string that doesn't match what's actually required. The human approver
still makes the final call, but they're reviewing a letter that has
already passed a mechanical accuracy check, not a raw, unverified draft.

Deliberately conservative: this flags textual absence, not semantic
paraphrase quality. A letter that paraphrases "certified copy" as
"certified" and drops "copy" would still fail (name+form_type are
checked as substrings), which is the right failure mode here -- the
checklist must be exact, not merely close.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cases import Case, STAGE_LANGUAGE


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    code: str
    message: str


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def passed(self) -> bool:
        """Passes if there are no errors. Warnings don't block approval
        but are surfaced to the human reviewer."""
        return len(self.errors) == 0

    def add(self, severity: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(severity=severity, code=code, message=message))


# Phrases that signal the letter has drifted into legal advice or
# outcome prediction -- outside the approved-language boundary even if
# no single word is individually forbidden. Conservative and short by
# design: false positives here just mean an extra warning for a human
# to glance at, not a silent block.
_ADVICE_SIGNAL_PATTERNS = [
    r"\bguarantee(s|d)?\b",
    r"\byou will (definitely|certainly|surely)\b",
    r"\bwe (recommend|advise) (that )?you\b",
    r"\bin our (legal )?opinion\b",
    r"\byour case (will|should) (be approved|win|succeed)\b",
    r"\bno risk\b",
]


def validate_letter(case: Case, letter_text: str) -> ValidationResult:
    """Check a generated letter's text against the case's true current
    state. Call this after drafting and before approval; surface
    `result.errors` to the approver (or block export outright) and
    `result.warnings` as advisory notes.
    """
    result = ValidationResult()
    text = letter_text or ""
    text_lower = text.lower()

    if not text.strip():
        result.add("error", "empty_letter", "The generated letter is empty.")
        return result

    _check_outstanding_documents_present(case, text, result)
    _check_received_documents_not_listed_as_outstanding(case, text_lower, result)
    _check_stage_language_present(case, text, result)
    _check_advice_language_absent(text_lower, result)

    return result


def _check_outstanding_documents_present(case: Case, text: str, result: ValidationResult) -> None:
    """Every currently-outstanding document's name AND exact form_type
    must appear in the letter text. Missing either is an error -- a
    dropped checklist item is exactly the failure mode this project
    exists to prevent."""
    for doc in case.outstanding_documents():
        name_present = doc.name.lower() in text.lower()
        form_type_present = doc.form_type.lower() in text.lower() if doc.form_type else True
        if not name_present:
            result.add(
                "error", "missing_outstanding_document",
                f"Outstanding document '{doc.name}' does not appear in the letter text.",
            )
        elif not form_type_present:
            result.add(
                "error", "missing_form_type",
                f"'{doc.name}' appears in the letter, but its required form "
                f"('{doc.form_type}') does not -- the exact-form requirement may have been dropped.",
            )


def _check_received_documents_not_listed_as_outstanding(case: Case, text_lower: str, result: ValidationResult) -> None:
    """A document already marked received should not be presented to the
    client as something they still owe. This is a heuristic (name-based
    substring match near checklist-style phrasing), so it's a warning,
    not a hard error -- the document name may legitimately appear
    elsewhere in the letter (e.g. "thank you for sending your Passport")."""
    outstanding_names = {d.name.lower() for d in case.outstanding_documents()}
    for doc in case.required_documents:
        if not doc.received:
            continue
        if doc.name.lower() in outstanding_names:
            continue  # can't happen given the model, but keep the guard explicit
        if doc.name.lower() in text_lower:
            # Only flag if it appears in a checklist-like context (bullet
            # marker or "outstanding"/"still need" nearby), to avoid
            # false positives on "thank you for your Passport" phrasing.
            pattern = re.compile(
                rf"(outstanding|still (need|owe)|missing|please (send|provide))[\s\S]{{0,150}}?{re.escape(doc.name.lower())}"
                rf"|{re.escape(doc.name.lower())}[\s\S]{{0,150}}?(outstanding|still (need|owe)|missing)"
            )
            if pattern.search(text_lower):
                result.add(
                    "warning", "received_document_listed_as_outstanding",
                    f"'{doc.name}' is marked received on file, but the letter appears to "
                    f"list it alongside outstanding-document language. Verify before sending.",
                )


def _check_stage_language_present(case: Case, text: str, result: ValidationResult) -> None:
    """The stage summary and next-step text must appear verbatim (or as
    a very close match) -- this is the approved-language boundary for
    stage description, and it should never be paraphrased by the AI."""
    expected_summary = STAGE_LANGUAGE[case.stage]["summary"]
    expected_next = STAGE_LANGUAGE[case.stage]["next"]

    if not _contains_normalized(text, expected_summary):
        result.add(
            "error", "stage_summary_not_verbatim",
            "The letter does not contain the approved stage-summary language verbatim "
            f"for stage {case.stage!r}. Expected: \"{expected_summary}\"",
        )
    if not _contains_normalized(text, expected_next):
        result.add(
            "error", "stage_next_step_not_verbatim",
            "The letter does not contain the approved next-step language verbatim "
            f"for stage {case.stage!r}. Expected: \"{expected_next}\"",
        )


def _check_advice_language_absent(text_lower: str, result: ValidationResult) -> None:
    for pattern in _ADVICE_SIGNAL_PATTERNS:
        if re.search(pattern, text_lower):
            result.add(
                "warning", "possible_advice_language",
                f"The letter contains language matching a legal-advice/outcome-prediction "
                f"signal pattern ({pattern!r}). Review before approving.",
            )


def _contains_normalized(haystack: str, needle: str) -> bool:
    """Whitespace-normalized substring match -- tolerates the AI
    reflowing line breaks or collapsing double spaces around the
    verbatim text, without tolerating actual paraphrase."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip().lower()
    return norm(needle) in norm(haystack)
