from __future__ import annotations

from core.models import (
    EntryStatus,
    ParseResult,
)
from core.validation import (
    CoverageReport,
    validate_coverage,
)


MISSING_RESPONSE_TEXT = (
    "⚠ Missing response in source notes — "
    "human input required."
)


def _assert_safe_to_render(
    coverage: CoverageReport,
) -> None:
    """
    Never present a cheatsheet as complete when
    objection coverage failed.
    """

    if coverage.is_complete:
        return

    problems: list[str] = []

    if coverage.dropped_objection_source_ids:
        problems.append(
            "dropped objections: "
            + ", ".join(
                coverage.dropped_objection_source_ids
            )
        )

    if coverage.duplicate_source_assignments:
        problems.append(
            "duplicate source assignments: "
            + ", ".join(
                coverage.duplicate_source_assignments
            )
        )

    detail = (
        "; ".join(problems)
        if problems
        else "coverage validation failed"
    )

    raise ValueError(
        "Cheatsheet generation blocked: "
        + detail
    )


def build_cheatsheet_markdown(
    result: ParseResult,
    title: str = "Objection Handling Cheatsheet",
) -> str:
    """
    Produce a uniform cheatsheet without inventing
    objection or response content.

    Source objection/response wording is preserved.
    Missing responses receive only an explicit status
    warning, never a generated sales answer.
    """

    coverage = validate_coverage(
        result
    )

    _assert_safe_to_render(
        coverage
    )

    lines: list[str] = [
        f"# {title}",
        "",
    ]

    for index, entry in enumerate(
        result.entries,
        start=1,
    ):
        lines.extend(
            [
                f"## {index}. {entry.objection}",
                "",
                "**Response**",
                "",
            ]
        )

        if (
            entry.status
            == EntryStatus.COMPLETE
            and entry.response
        ):
            lines.append(
                entry.response
            )
        else:
            lines.append(
                MISSING_RESPONSE_TEXT
            )

        lines.extend(
            [
                "",
                "---",
                "",
            ]
        )

    return "\n".join(
        lines
    ).rstrip() + "\n"


def build_coverage_summary(
    result: ParseResult,
) -> dict[str, int | bool]:
    """
    Small UI-friendly summary.
    """

    coverage = validate_coverage(
        result
    )

    return {
        "detected_objections":
            coverage.detected_objection_count,

        "output_blocks":
            coverage.output_block_count,

        "complete_responses":
            coverage.complete_count,

        "missing_responses":
            coverage.missing_response_count,

        "unassigned_source_items":
            coverage.unassigned_source_count,

        "dropped_objections":
            len(
                coverage.dropped_objection_source_ids
            ),

        "duplicate_assignments":
            len(
                coverage.duplicate_source_assignments
            ),

        "coverage_passed":
            coverage.is_complete,
    }