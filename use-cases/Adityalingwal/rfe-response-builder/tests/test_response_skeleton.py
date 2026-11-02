import pytest

from engine.coverage_checklist import build_checklist
from engine.draft_instruction import build_draft_instruction
from engine.requests_from_notice import parse_notice
from engine.response_skeleton import (
    DRAFT_PLACEHOLDER_PREFIX,
    build_skeleton,
    draft_placeholder,
)
from engine.retrieve_petition_material import retrieve
from engine.verify_citations import citation_is_verbatim


@pytest.fixture(scope="module")
def skeleton(notice_text, sections, retrieval_config):
    requests = parse_notice(notice_text)
    matches = retrieve(requests, sections, retrieval_config)
    checklist = build_checklist(requests, matches, retrieval_config)
    return build_skeleton(requests, checklist)


def test_every_notice_request_has_a_response_section_and_placeholder(
    skeleton, notice_text
):
    requests = parse_notice(notice_text)
    for request in requests:
        assert f"Response to Request {request.id[1:]} — {request.title}" in skeleton
        assert draft_placeholder(request.id) in skeleton
    assert skeleton.count(DRAFT_PLACEHOLDER_PREFIX) == len(requests)


def test_the_not_provided_section_carries_the_honest_gap_note(skeleton):
    assert "no material addressing this request" in skeleton
    assert "needs attorney confirmation" in skeleton


def test_every_skeleton_excerpt_is_verbatim_petition_text(
    skeleton, petition, notice_text, sections, retrieval_config
):
    requests = parse_notice(notice_text)
    matches = retrieve(requests, sections, retrieval_config)
    for found in matches.values():
        for match in found:
            assert citation_is_verbatim(match.excerpt[:300], petition[match.file])


def test_the_draft_instruction_pins_its_safety_rules():
    instruction = build_draft_instruction()
    assert DRAFT_PLACEHOLDER_PREFIX in instruction
    assert "ENTIRE text is a placeholder" in instruction
    assert "Never edit the paragraphs that begin with" in instruction
    assert "ONLY the petition material" in instruction
    assert "Never claim that evidence, data, or an exhibit exists" in instruction
    assert "Never write as if the missing evidence exists" in instruction
    assert "Coverage checklist table" in instruction
    assert "the attachments never license a new claim" in instruction


def test_a_blockquote_excerpt_flattens_without_stranded_markers():
    from engine.response_skeleton import _trimmed

    flattened = _trimmed("> salary is $120,000\n> paid bi-weekly")
    assert flattened == "salary is $120,000 paid bi-weekly"
