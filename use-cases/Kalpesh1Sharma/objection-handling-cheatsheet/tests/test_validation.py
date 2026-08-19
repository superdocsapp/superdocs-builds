from core.models import (
    EntryStatus,
    ObjectionEntry,
    ParseResult,
    SourceUnit,
)
from core.parser import parse_objection_notes
from core.validation import validate_coverage


def test_complete_parse_has_zero_dropped_objections():
    result = parse_objection_notes(
        [
            "- Too expensive",
            "resp: Start small.",
            "- Security?",
            "resp: Data is encrypted.",
        ]
    )

    coverage = validate_coverage(
        result
    )

    assert (
        coverage.detected_objection_count
        == 2
    )

    assert (
        coverage.output_block_count
        == 2
    )

    assert (
        coverage.dropped_objection_source_ids
        == []
    )

    assert coverage.is_complete is True


def test_missing_response_is_not_dropped():
    result = parse_objection_notes(
        [
            "- Too expensive",
            "resp: Start small.",
            "- Implementation risk",
        ]
    )

    coverage = validate_coverage(
        result
    )

    assert (
        coverage.detected_objection_count
        == 2
    )

    assert (
        coverage.output_block_count
        == 2
    )

    assert (
        coverage.missing_response_count
        == 1
    )

    assert (
        coverage.dropped_objection_source_ids
        == []
    )

    assert coverage.is_complete is True


def test_unassigned_source_is_reported():
    result = parse_objection_notes(
        [
            "resp: orphan response",
            "- Security?",
            "resp: Data is encrypted.",
        ]
    )

    coverage = validate_coverage(
        result
    )

    assert (
        coverage.unassigned_source_count
        == 1
    )


def test_duplicate_source_assignment_is_detected():
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
                status=EntryStatus.MISSING_RESPONSE,
                objection_source_ids=[
                    "SRC-001"
                ],
            ),
            ObjectionEntry(
                entry_id="OBJ-002",
                objection="Security again?",
                response=None,
                status=EntryStatus.MISSING_RESPONSE,
                objection_source_ids=[
                    "SRC-001"
                ],
            ),
        ],
    )

    coverage = validate_coverage(
        result
    )

    assert (
        coverage.duplicate_source_assignments
        == ["SRC-001"]
    )

    assert coverage.is_complete is False


def test_detected_but_missing_output_is_caught():
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
                text="- Too expensive",
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
                status=EntryStatus.MISSING_RESPONSE,
                objection_source_ids=[
                    "SRC-001"
                ],
            ),
        ],
    )

    coverage = validate_coverage(
        result
    )

    assert (
        coverage.detected_objection_count
        == 2
    )

    assert (
        coverage.output_block_count
        == 1
    )

    assert (
        coverage.dropped_objection_source_ids
        == ["SRC-002"]
    )

    assert coverage.is_complete is False