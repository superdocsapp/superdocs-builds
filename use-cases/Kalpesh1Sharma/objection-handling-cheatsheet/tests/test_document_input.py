from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.cheatsheet import (
    MISSING_RESPONSE_TEXT,
    build_cheatsheet_markdown,
)
from core.document_input import (
    read_docx_lines,
)
from core.parser import (
    parse_objection_notes,
)
from core.validation import (
    validate_coverage,
)


BASE_DIR = Path(
    "sample_documents"
)


def _load_ground_truth(
    scenario: str,
) -> dict:
    path = (
        BASE_DIR
        / scenario
        / "ground_truth.json"
    )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def test_scenario_a_real_docx_matches_ground_truth():
    docx_path = (
        BASE_DIR
        / "scenario_a"
        / "messy_objection_notes.docx"
    )

    lines = read_docx_lines(
        docx_path
    )

    result = parse_objection_notes(
        lines
    )

    coverage = validate_coverage(
        result
    )

    truth = _load_ground_truth(
        "scenario_a"
    )

    assert (
        coverage.detected_objection_count
        == truth[
            "expected_objection_count"
        ]
    )

    assert (
        coverage.output_block_count
        == truth[
            "expected_objection_count"
        ]
    )

    assert (
        coverage.complete_count
        == truth[
            "expected_complete_count"
        ]
    )

    assert (
        coverage.missing_response_count
        == truth[
            "expected_missing_response_count"
        ]
    )

    assert (
        len(
            coverage.dropped_objection_source_ids
        )
        == truth[
            "expected_dropped_count"
        ]
    )

    assert coverage.is_complete is True

    assert [
        entry.objection
        for entry in result.entries
    ] == [
        item["objection"]
        for item in truth["entries"]
    ]

    assert [
        entry.response
        for entry in result.entries
    ] == [
        item["response"]
        for item in truth["entries"]
    ]


def test_scenario_b_real_docx_matches_ground_truth():
    docx_path = (
        BASE_DIR
        / "scenario_b"
        / "different_format_notes.docx"
    )

    lines = read_docx_lines(
        docx_path
    )

    result = parse_objection_notes(
        lines
    )

    coverage = validate_coverage(
        result
    )

    truth = _load_ground_truth(
        "scenario_b"
    )

    assert (
        coverage.detected_objection_count
        == truth[
            "expected_objection_count"
        ]
    )

    assert (
        coverage.output_block_count
        == truth[
            "expected_objection_count"
        ]
    )

    assert (
        coverage.complete_count
        == truth[
            "expected_complete_count"
        ]
    )

    assert (
        coverage.missing_response_count
        == truth[
            "expected_missing_response_count"
        ]
    )

    assert (
        len(
            coverage.dropped_objection_source_ids
        )
        == truth[
            "expected_dropped_count"
        ]
    )

    assert coverage.is_complete is True

    assert [
        entry.objection
        for entry in result.entries
    ] == [
        item["objection"]
        for item in truth["entries"]
    ]

    assert [
        entry.response
        for entry in result.entries
    ] == [
        item["response"]
        for item in truth["entries"]
    ]


def test_real_scenario_a_missing_response_is_not_invented():
    path = (
        BASE_DIR
        / "scenario_a"
        / "messy_objection_notes.docx"
    )

    result = parse_objection_notes(
        read_docx_lines(
            path
        )
    )

    missing = [
        entry
        for entry in result.entries
        if entry.response is None
    ]

    assert len(missing) == 1

    assert (
        missing[0].objection
        == "Implementation looks complicated"
    )

    output = build_cheatsheet_markdown(
        result
    )

    assert (
        MISSING_RESPONSE_TEXT
        in output
    )


def test_real_scenario_b_missing_response_is_not_invented():
    path = (
        BASE_DIR
        / "scenario_b"
        / "different_format_notes.docx"
    )

    result = parse_objection_notes(
        read_docx_lines(
            path
        )
    )

    missing = [
        entry
        for entry in result.entries
        if entry.response is None
    ]

    assert len(missing) == 1

    assert (
        missing[0].objection
        == "Worried about onboarding"
    )


def test_docx_reader_rejects_unsupported_format(
    tmp_path,
):
    path = (
        tmp_path
        / "notes.txt"
    )

    path.write_text(
        "Some notes",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported local input format",
    ):
        read_docx_lines(
            path
        )