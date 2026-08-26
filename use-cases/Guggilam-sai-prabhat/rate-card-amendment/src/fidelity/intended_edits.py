"""Derives the intended-edit set from an `AmendmentCase`'s SuperDocs proposal.

The only authoritative source of "what was supposed to change" is the case
itself: `case.pending_changes` (what SuperDocs proposed, each with a
`chunk_id` and literal `old_html`/`new_html`) and `case.approvals` (the
human decision per `change_id`, recorded via
`src/amendment_case.py::record_decision`). This module does not re-derive
intent from the exported document — that would make the fidelity check
circular (comparing the export against a summary of itself).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.amendment_case import AmendmentCase
from src.case_state import CaseState
from src.fidelity.document_model import parse_document


class EditDisposition(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class IntendedEdit:
    """One rate-table edit SuperDocs proposed, and its human disposition.

    `should_appear_in_export` is True only for APPROVED edits — an
    unintended-diff classifier uses this to decide whether a given change's
    `new_html` fragment is expected to be present in the final export.
    """

    change_id: str
    chunk_id: str
    old_fragment: Optional[str]
    new_fragment: Optional[str]
    disposition: EditDisposition
    ai_explanation: Optional[str]

    @property
    def should_appear_in_export(self) -> bool:
        return self.disposition == EditDisposition.APPROVED

    def old_text(self) -> str:
        return parse_document(self.old_fragment or "", format_hint="html").raw_text

    def new_text(self) -> str:
        return parse_document(self.new_fragment or "", format_hint="html").raw_text


def derive_intended_edits(case: AmendmentCase) -> list[IntendedEdit]:
    """Build the intended-edit list from a case's pending changes + decisions.

    Every `pending_change` produces exactly one `IntendedEdit`, regardless
    of the case's current state — callers that only want the edits that
    should actually be visible in an export should filter on
    `should_appear_in_export`, not assume this function does that filtering
    (a fidelity report needs to see rejected/unresolved edits too, to prove
    they did *not* land).
    """

    edits: list[IntendedEdit] = []
    for change in case.pending_changes:
        decision = case.approvals.get(change.change_id)
        if decision is True:
            disposition = EditDisposition.APPROVED
        elif decision is False:
            disposition = EditDisposition.REJECTED
        else:
            disposition = EditDisposition.UNRESOLVED
        edits.append(
            IntendedEdit(
                change_id=change.change_id,
                chunk_id=change.chunk_id,
                old_fragment=change.old_html,
                new_fragment=change.new_html,
                disposition=disposition,
                ai_explanation=change.ai_explanation,
            )
        )
    return edits


def expected_touched_chunk_ids(case: AmendmentCase) -> set[str]:
    """Chunk ids that an approved edit legitimately touched.

    Distinct from `src.amendment_case.touched_chunk_ids`, which returns
    *every* chunk id SuperDocs proposed touching regardless of decision —
    this narrows to only the chunks whose edit was actually approved, i.e.
    the set that should show up as changed in the final export.
    """

    return {e.chunk_id for e in derive_intended_edits(case) if e.should_appear_in_export}


def case_should_have_no_diff(case: AmendmentCase) -> bool:
    """True when no approved edit exists, so the export must equal the
    original byte-for-byte-of-content (e.g. every proposal rejected, or a
    pricing-lock/mutual-consent case that never reached SuperDocs and whose
    "export" is just the original file — see `export_case` in
    `app/backend/routes/results.py`)."""

    if case.state in (CaseState.BLOCKED, CaseState.REQUIRES_REVIEW, CaseState.FAILED):
        return True
    return len(expected_touched_chunk_ids(case)) == 0
