import pytest

from core.cheatsheet import (
    MISSING_RESPONSE_TEXT,
    build_cheatsheet_markdown,
    build_coverage_summary,
)
from core.models import (
    EntryStatus,
    ObjectionEntry,
    ParseResult,
    SourceUnit,
)
from core.parser import (
    parse_objection_notes,
)


def test_cheatsheet_has_one_block_per_objection():
    result = parse_objection_notes(
        [
            "- Too expensive",
            "resp: Start small.",
            "- Security?",
            "resp: Data is encrypted.",
        ]
    )

    output = build_cheatsheet_markdown(
        result
    )

    assert "## 1. Too expensive" in output
    assert "## 2. Security?" in output

    assert (
        output.count("**Response**")
        == 2
    )


def test_source_wording_is_preserved():
    result = parse_objection_notes(
        [
            "- SECURITY???",
            (
                "resp: We encrypt data "
                "in transit and at rest."
            ),
        ]
    )

    output = build_cheatsheet_markdown(
        result
    )

    assert "SECURITY???" in output

    assert (
        "We encrypt data in transit "
        "and at rest."
        in output
    )


def test_missing_response_is_flagged_not_invented():
    result = parse_objection_notes(
        [
            "- Implementation looks complicated",
        ]
    )

    output = build_cheatsheet_markdown(
        result
    )

    assert (
        "Implementation looks complicated"
        in output
    )

    assert (
        MISSING_RESPONSE_TEXT
        in output
    )

    entry = result.entries[0]

    assert entry.response is None

    assert (
        entry.status
        == EntryStatus.MISSING_RESPONSE
    )


def test_duplicate_objections_remain_separate_blocks():
    result = parse_objection_notes(
        [
            "- Too expensive",
            "resp: Start small.",
            "- Too expensive",
            "resp: Offer a pilot.",
        ]
    )

    output = build_cheatsheet_markdown(
        result
    )

    assert (
        output.count("Too expensive")
        == 2
    )

    assert "Start small." in output
    assert "Offer a pilot." in output


def test_coverage_summary_reports_counts():
    result = parse_objection_notes(
        [
            "- Price",
            "resp: Start small.",
            "- Security?",
        ]
    )

    summary = build_coverage_summary(
        result
    )

    assert (
        summary["detected_objections"]
        == 2
    )

    assert (
        summary["output_blocks"]
        == 2
    )

    assert (
        summary["complete_responses"]
        == 1
    )

    assert (
        summary["missing_responses"]
        == 1
    )

    assert (
        summary["dropped_objections"]
        == 0
    )

    assert (
        summary["coverage_passed"]
        is True
    )


def test_render_is_blocked_if_objection_was_dropped():
    result = ParseResult(
        source_units=[
            SourceUnit(
                source_id="SRC-001",
                position=1,
                text="- Security?",
            ),
            SourceUnit(
                source_id="SRC-002",
                position=2,
                text="- Price?",
            ),
        ],

        detected_objection_source_ids=[
            "SRC-001",
            "SRC-002",
        ],

        entries=[
            ObjectionEntry(
                entry_id="OBJ-001",
                objection="Security?",
                response=None,
                status=(
                    EntryStatus.MISSING_RESPONSE
                ),
                objection_source_ids=[
                    "SRC-001"
                ],
            )
        ],
    )

    with pytest.raises(
        ValueError,
        match="dropped objections",
    ):
        build_cheatsheet_markdown(
            result
        )


def test_render_is_blocked_on_duplicate_source_assignment():
    result = ParseResult(
        source_units=[
            SourceUnit(
                source_id="SRC-001",
                position=1,
                text="- Security?",
            ),
        ],

        detected_objection_source_ids=[
            "SRC-001"
        ],

        entries=[
            ObjectionEntry(
                entry_id="OBJ-001",
                objection="Security?",
                response=None,
                status=(
                    EntryStatus.MISSING_RESPONSE
                ),
                objection_source_ids=[
                    "SRC-001"
                ],
            ),

            ObjectionEntry(
                entry_id="OBJ-002",
                objection="Security duplicate?",
                response=None,
                status=(
                    EntryStatus.MISSING_RESPONSE
                ),
                objection_source_ids=[
                    "SRC-001"
                ],
            ),
        ],
    )

    with pytest.raises(
        ValueError,
        match="duplicate source assignments",
    ):
        build_cheatsheet_markdown(
            result
        )