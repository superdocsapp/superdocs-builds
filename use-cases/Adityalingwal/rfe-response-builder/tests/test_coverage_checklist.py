import pytest

from engine.coverage_checklist import build_checklist
from engine.model import Coverage
from engine.requests_from_notice import parse_notice
from engine.retrieve_petition_material import retrieve


@pytest.fixture(scope="module")
def checklist(notice_text, sections, retrieval_config):
    requests = parse_notice(notice_text)
    matches = retrieve(requests, sections, retrieval_config)
    return build_checklist(requests, matches, retrieval_config)


def coverage_of(checklist, request_id):
    return next(r for r in checklist if r.request_id == request_id).coverage


def test_requests_with_petition_material_are_answered(checklist):
    assert coverage_of(checklist, "R1") == Coverage.ANSWERED
    assert coverage_of(checklist, "R2") == Coverage.ANSWERED
    assert coverage_of(checklist, "R3") == Coverage.ANSWERED


def test_vaguely_covered_request_is_partial_never_answered(checklist):
    assert coverage_of(checklist, "R4") == Coverage.PARTIAL


def test_uncovered_request_is_honestly_not_provided(checklist):
    row = next(r for r in checklist if r.request_id == "R5")
    assert row.coverage == Coverage.NOT_PROVIDED
    assert "attorney" in row.reason


def test_every_notice_request_stays_on_the_checklist(checklist, notice_text):
    requests = parse_notice(notice_text)
    assert [row.request_id for row in checklist] == [r.id for r in requests]


def test_no_match_excerpt_is_invented_all_come_from_petition_files(
    checklist, petition
):
    for row in checklist:
        for match in row.matches:
            assert match.file in petition
            assert match.excerpt in petition[match.file]
