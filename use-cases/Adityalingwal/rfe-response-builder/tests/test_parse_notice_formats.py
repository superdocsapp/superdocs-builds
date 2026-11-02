from pathlib import Path

import pytest

from engine.model import ChecklistRow, Coverage
from engine.requests_from_notice import parse_notice
from engine.response_skeleton import build_skeleton

FIXTURES = Path(__file__).parent / "fixtures"

TWO_GROUP_NOTICE = """# REQUEST FOR EVIDENCE

A. Specialty occupation

1. Submit a detailed description of the offered position and its duties.

2. Submit the employer's organizational chart naming the supervisor.

B. Beneficiary qualifications

1. Submit the beneficiary's degree certificate and full transcripts.

2. Submit a credentials evaluation of the beneficiary's foreign degree.
"""

ITEM_NOTICE_WITH_A_CAPS_SUB_LINE = """# REQUEST FOR EVIDENCE

## ITEM 1 — Specialty occupation

The petition must establish that the offered position qualifies as a
specialty occupation.

SUPPORTING DOCUMENTATION

Submit a detailed position description signed by the employer.
Submit the organizational chart naming the beneficiary's supervisor.

## ITEM 2 — Beneficiary qualifications

Submit the beneficiary's degree certificate and full transcripts.

HOW TO RESPOND

Return this notice with your response by the deadline printed above.
"""


@pytest.fixture(scope="module")
def style_b():
    return (FIXTURES / "notice-style-b-numbered-list.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def style_c():
    return (FIXTURES / "notice-style-c-request-labels.md").read_text(encoding="utf-8")


def test_a_plain_numbered_list_notice_yields_the_same_five_requests(style_b):
    requests = parse_notice(style_b)
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5"]
    assert "nonimmigrant" in requests[4].text


def test_a_request_labelled_notice_yields_the_same_five_requests(style_c):
    requests = parse_notice(style_c)
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4", "R5"]
    assert "specialty occupation" in requests[1].text


def test_no_request_is_invented_in_any_supported_style(style_b, style_c):
    for notice in (style_b, style_c):
        for request in parse_notice(notice):
            assert request.text in notice


def test_every_style_gives_each_request_a_usable_title(style_b, style_c):
    for notice in (style_b, style_c):
        for request in parse_notice(notice):
            assert request.title.strip()


def test_a_notice_that_restarts_its_numbering_per_group_still_gives_distinct_ids():
    requests = parse_notice(TWO_GROUP_NOTICE)
    assert [r.id for r in requests] == ["R1", "R2", "R3", "R4"]


def test_every_request_of_a_restarted_numbering_notice_keeps_its_own_section():
    requests = parse_notice(TWO_GROUP_NOTICE)
    checklist = [
        ChecklistRow(
            request_id=request.id,
            title=request.title,
            coverage=Coverage.NOT_PROVIDED,
            reason="no petition material located",
        )
        for request in requests
    ]
    skeleton = build_skeleton(requests, checklist)
    numbered = [
        line.split()[4]
        for line in skeleton.splitlines()
        if line.startswith("## Response to Request ")
    ]
    assert numbered == ["1", "2", "3", "4"]


def test_a_caps_sub_line_does_not_cut_a_request_that_the_next_item_already_bounds():
    requests = parse_notice(ITEM_NOTICE_WITH_A_CAPS_SUB_LINE)
    assert [r.id for r in requests] == ["R1", "R2"]
    assert "SUPPORTING DOCUMENTATION" in requests[0].text
    assert "detailed position description" in requests[0].text
    assert "organizational chart" in requests[0].text


def test_the_closing_caps_section_is_still_kept_out_of_the_last_request():
    for request in parse_notice(ITEM_NOTICE_WITH_A_CAPS_SUB_LINE):
        assert "HOW TO RESPOND" not in request.text
        assert "Return this notice" not in request.text
