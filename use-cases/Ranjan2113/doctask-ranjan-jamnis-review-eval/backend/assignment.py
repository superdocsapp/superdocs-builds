"""Latin-square assignment of reviewers to conditions and batches.

PLAN.md.pdf section 2: within-subject 2x2. Every reviewer sees all four
conditions, each on a *different* document, in a counterbalanced order so
learning effects distribute across conditions rather than piling onto whichever
one happens to come last.

The two factors:
  Presentation    batch      (all changes at once, submit together)
                  sequential (one change at a time, forced order)
  Diff granularity section   (just the changed chunk, before/after)
                  whole      (changed chunk highlighted inside the full document)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONDITIONS: tuple[str, ...] = (
    "batch_section",
    "batch_whole",
    "sequential_section",
    "sequential_whole",
)


class AssignmentError(RuntimeError):
    """The requested design cannot be built from the corpus available."""


@dataclass(frozen=True)
class Cell:
    """One reviewer's work on one condition."""

    reviewer_id: str
    position: int  # 0-based order in which this reviewer sees it
    condition: str
    batch_id: str


def latin_square(n: int) -> list[list[int]]:
    """Cyclic Latin square of order n.

    Row i is the sequence rotated left by i, so each item appears exactly once
    in every position across the n rows. That is what balances order effects:
    with n reviewers each condition occupies each slot exactly once.
    """
    return [[(i + j) % n for j in range(n)] for i in range(n)]


def build_assignments(
    reviewer_ids: list[str],
    batch_ids: list[str],
    conditions: tuple[str, ...] = CONDITIONS,
    *,
    allow_partial: bool = False,
) -> list[Cell]:
    """Pair each reviewer's condition order with a distinct batch.

    A reviewer must never see the same change twice: once they have judged a
    change, their second judgment of it is contaminated by memory, and both
    their decision time and their agreement with other reviewers stop measuring
    what we claim they measure. So each condition needs its own batch, and the
    design requires at least as many batches as conditions.

    `allow_partial=True` relaxes this for the pilot, where only one document
    exists: each reviewer is given as many conditions as there are batches.
    """
    if not reviewer_ids:
        raise AssignmentError("no reviewers to assign")
    if not batch_ids:
        raise AssignmentError("no batches to assign")

    n_cond = len(conditions)
    if len(batch_ids) < n_cond and not allow_partial:
        raise AssignmentError(
            f"design needs one batch per condition: {n_cond} conditions but only "
            f"{len(batch_ids)} batch(es). Build more documents, or pass "
            f"allow_partial=True to run a reduced pilot."
        )

    # How many conditions each reviewer can actually complete without ever
    # meeting the same batch twice.
    width = min(n_cond, len(batch_ids))
    square = latin_square(n_cond)

    # The square is: rows = reviewers, columns = documents, cells = conditions.
    # Document is fixed to position so that rotating the condition row is the
    # only thing that varies -- which is what makes condition orthogonal to
    # both running order and document.
    #
    # An earlier version rotated the batch by reviewer as well, which made the
    # condition index and the batch index identical: every reviewer met
    # batch_section on b0, batch_whole on b1, and so on. Condition and document
    # were then perfectly confounded, and any difference between conditions
    # would really have been a difference between documents.
    # test_condition_is_not_confounded_with_document pins this.
    cells: list[Cell] = []
    for r_index, reviewer_id in enumerate(reviewer_ids):
        order = square[r_index % n_cond]
        for position in range(width):
            cells.append(
                Cell(
                    reviewer_id=reviewer_id,
                    position=position,
                    condition=conditions[order[position]],
                    batch_id=batch_ids[position % len(batch_ids)],
                )
            )
    return cells


def assignments_to_dict(cells: list[Cell]) -> dict[str, Any]:
    by_reviewer: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        by_reviewer.setdefault(cell.reviewer_id, []).append(
            {
                "position": cell.position,
                "condition": cell.condition,
                "batch_id": cell.batch_id,
            }
        )
    for entries in by_reviewer.values():
        entries.sort(key=lambda e: e["position"])
    return {"conditions": list(CONDITIONS), "reviewers": by_reviewer}


def check_balance(cells: list[Cell]) -> dict[str, dict[str, int]]:
    """How often each condition lands in each position. For the write-up.

    With a full square and a multiple-of-4 panel these are all equal; with 3 or
    5 reviewers they are not, and the write-up should say so rather than claim
    a balance the design did not achieve.
    """
    table: dict[str, dict[str, int]] = {}
    for cell in cells:
        table.setdefault(cell.condition, {})
        key = f"position_{cell.position}"
        table[cell.condition][key] = table[cell.condition].get(key, 0) + 1
    return table
