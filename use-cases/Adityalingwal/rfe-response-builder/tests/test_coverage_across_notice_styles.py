from pathlib import Path

import pytest

from engine.coverage_checklist import build_checklist
from engine.model import Coverage
from engine.requests_from_notice import parse_notice
from engine.retrieve_petition_material import retrieve

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED = {
    "R1": Coverage.ANSWERED,
    "R2": Coverage.ANSWERED,
    "R3": Coverage.ANSWERED,
    "R4": Coverage.PARTIAL,
    "R5": Coverage.NOT_PROVIDED,
}


@pytest.mark.parametrize(
    "fixture",
    ["notice-style-b-numbered-list.md", "notice-style-c-request-labels.md"],
)
def test_every_notice_style_reaches_the_same_honest_buckets(
    fixture, sections, retrieval_config
):
    notice = (FIXTURES / fixture).read_text(encoding="utf-8")
    requests = parse_notice(notice)
    matches = retrieve(requests, sections, retrieval_config)
    checklist = build_checklist(requests, matches, retrieval_config)
    got = {row.request_id: row.coverage for row in checklist}
    assert got == EXPECTED


def test_a_terse_two_word_request_is_never_marked_answered(
    sections, retrieval_config
):
    # A tiny request can overlap a section 100% on a couple of words; the
    # shared-stems floor keeps that conservative (partial at most), because
    # "answered" claims real material, and two words prove nothing.
    notice = (
        "# NOTICE\n\nEvidence requested:\n\n"
        "1. Submit evidence of the specialty occupation.\n\n"
        "2. Submit evidence of the employer-employee relationship.\n"
    )
    requests = parse_notice(notice)
    matches = retrieve(requests, sections, retrieval_config)
    checklist = build_checklist(requests, matches, retrieval_config)
    for row in checklist:
        assert row.coverage != Coverage.ANSWERED
