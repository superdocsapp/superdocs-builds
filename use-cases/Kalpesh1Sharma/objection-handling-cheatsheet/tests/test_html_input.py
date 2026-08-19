from pathlib import Path

from core.cheatsheet import (
    build_coverage_summary,
)
from core.html_input import (
    extract_lines_from_superdocs_html,
)
from core.parser import (
    parse_objection_notes,
)


FIXTURE = (
    Path("tests")
    / "fixtures"
    / "scenario_a_superdocs.html"
)


def test_real_superdocs_html_preserves_order():
    html = FIXTURE.read_text(
        encoding="utf-8"
    )

    lines = (
        extract_lines_from_superdocs_html(
            html
        )
    )

    assert lines[0] == (
        "Random sales call notes"
    )

    assert lines[1] == (
        "- It's too expensive"
    )

    assert lines[2] == (
        "resp: Start with a small pilot "
        "rather than a full rollout."
    )


def test_html_entities_are_decoded():
    html = FIXTURE.read_text(
        encoding="utf-8"
    )

    lines = (
        extract_lines_from_superdocs_html(
            html
        )
    )

    assert (
        "-> Migration can be phased "
        "alongside the existing workflow."
        in lines
    )


def test_real_superdocs_html_matches_expected_coverage():
    html = FIXTURE.read_text(
        encoding="utf-8"
    )

    lines = (
        extract_lines_from_superdocs_html(
            html
        )
    )

    result = parse_objection_notes(
        lines
    )

    summary = build_coverage_summary(
        result
    )

    assert (
        summary["detected_objections"]
        == 6
    )

    assert (
        summary["output_blocks"]
        == 6
    )

    assert (
        summary["complete_responses"]
        == 5
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
        summary["duplicate_assignments"]
        == 0
    )

    assert (
        summary["coverage_passed"]
        is True
    )


def test_missing_response_survives_superdocs_round_trip():
    html = FIXTURE.read_text(
        encoding="utf-8"
    )

    result = parse_objection_notes(
        extract_lines_from_superdocs_html(
            html
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


def test_empty_html_is_rejected():
    try:
        extract_lines_from_superdocs_html(
            ""
        )
    except ValueError as exc:
        assert (
            "empty HTML"
            in str(exc)
        )
    else:
        raise AssertionError(
            "Expected ValueError."
        )