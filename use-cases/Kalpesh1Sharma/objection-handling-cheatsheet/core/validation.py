from __future__ import annotations

from collections import Counter

from pydantic import BaseModel

from core.models import ParseResult


class CoverageReport(BaseModel):
    detected_objection_count: int
    output_block_count: int
    complete_count: int
    missing_response_count: int

    assigned_source_count: int
    unassigned_source_count: int

    dropped_objection_source_ids: list[str]
    duplicate_source_assignments: list[str]

    is_complete: bool


def validate_coverage(
    result: ParseResult,
) -> CoverageReport:
    all_assigned_ids: list[str] = []

    assigned_objection_ids: list[str] = []

    for entry in result.entries:
        assigned_objection_ids.extend(
            entry.objection_source_ids
        )

        all_assigned_ids.extend(
            entry.objection_source_ids
        )

        all_assigned_ids.extend(
            entry.response_source_ids
        )

    counts = Counter(
        all_assigned_ids
    )

    duplicate_assignments = sorted(
        source_id
        for source_id, count in counts.items()
        if count > 1
    )

    detected_objection_ids = set(
        result.detected_objection_source_ids
    )

    assigned_objection_id_set = set(
        assigned_objection_ids
    )

    dropped_objections = sorted(
        detected_objection_ids
        - assigned_objection_id_set
    )

    detected_count = len(
        result.detected_objection_source_ids
    )

    output_count = len(
        result.entries
    )

    is_complete = (
        detected_count == output_count
        and not dropped_objections
        and not duplicate_assignments
    )

    return CoverageReport(
        detected_objection_count=(
            detected_count
        ),
        output_block_count=output_count,
        complete_count=result.complete_count,
        missing_response_count=(
            result.missing_response_count
        ),
        assigned_source_count=len(
            set(all_assigned_ids)
        ),
        unassigned_source_count=len(
            result.unassigned_source_ids
        ),
        dropped_objection_source_ids=(
            dropped_objections
        ),
        duplicate_source_assignments=(
            duplicate_assignments
        ),
        is_complete=is_complete,
    )