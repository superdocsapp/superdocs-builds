import json

import pytest

from engine.judge_coverage import (
    build_judge_instruction,
    judged_checklist,
    parse_judge_reply,
)
from engine.model import Coverage
from engine.requests_from_notice import parse_notice
from engine.retrieve_petition_material import retrieve


@pytest.fixture(scope="module")
def corpus(notice_text, sections, retrieval_config):
    requests = parse_notice(notice_text)
    matches = retrieve(requests, sections, retrieval_config)
    return requests, matches


def test_the_instruction_carries_every_request_and_marks_missing_material(corpus):
    requests, matches = corpus
    no_material = {**matches, "R5": []}
    instruction = build_judge_instruction(requests, no_material)
    for request in requests:
        assert f"Request {request.id}" in instruction
    assert "NONE found" in instruction


def test_the_instruction_pins_its_judging_rules(corpus):
    requests, matches = corpus
    instruction = build_judge_instruction(requests, matches)
    assert "ONLY from the material quoted" in instruction
    assert "dates, periods, places" in instruction
    assert "ONLY a JSON object" in instruction
    assert "Do not edit or create any document" in instruction


def scripted_reply(requests, coverages):
    return json.dumps(
        {
            r.id: {"coverage": cov, "reason": f"reason for {r.id}"}
            for r, cov in zip(requests, coverages)
        }
    )


def test_a_clean_judge_reply_becomes_the_checklist(corpus):
    requests, matches = corpus
    reply = scripted_reply(
        requests, ["answered", "answered", "answered", "partial", "not_provided"]
    )
    verdicts = parse_judge_reply(reply, requests)
    rows = judged_checklist(requests, matches, verdicts)
    assert [row.coverage for row in rows] == [
        Coverage.ANSWERED,
        Coverage.ANSWERED,
        Coverage.ANSWERED,
        Coverage.PARTIAL,
        Coverage.NOT_PROVIDED,
    ]


def test_prose_around_the_json_is_tolerated(corpus):
    requests, _ = corpus
    reply = "Here is my judgement:\n" + scripted_reply(requests, ["answered"] * 5)
    assert parse_judge_reply(reply, requests)["R1"][0] == Coverage.ANSWERED


def test_a_reply_that_skips_a_request_is_refused(corpus):
    requests, _ = corpus
    reply = scripted_reply(requests[:4], ["answered"] * 4)
    with pytest.raises(ValueError, match="R5"):
        parse_judge_reply(reply, requests)


def test_an_unknown_coverage_value_is_refused(corpus):
    requests, _ = corpus
    reply = scripted_reply(requests, ["answered", "maybe", "answered", "partial", "not_provided"])
    with pytest.raises(ValueError, match="maybe"):
        parse_judge_reply(reply, requests)


def test_a_reply_without_json_is_refused_naming_the_fix(corpus):
    requests, _ = corpus
    with pytest.raises(ValueError, match="model_tier"):
        parse_judge_reply("I think everything looks fine!", requests)


def test_a_huge_case_still_fits_the_chat_message_limit():
    from engine.judge_coverage import MESSAGE_CHAR_LIMIT
    from engine.model import Match, Request

    requests = [
        Request(id=f"R{i}", title=f"Request {i}", text="officer concern " * 200)
        for i in range(1, 13)
    ]
    matches = {
        r.id: [
            Match(
                request_id=r.id,
                file=f"doc-{j}.md",
                heading="section",
                excerpt="petition material words " * 400,
                score=0.5,
                shared_stems=9,
            )
            for j in range(6)
        ]
        for r in requests
    }
    instruction = build_judge_instruction(requests, matches)
    assert len(instruction) <= MESSAGE_CHAR_LIMIT
    for r in requests:
        assert f"Request {r.id}:" in instruction


def test_answered_without_located_material_is_overridden(corpus):
    requests, matches = corpus
    # a judge claiming "answered" where the locator found nothing invented it
    no_material = {**matches, "R5": []}
    reply = scripted_reply(requests, ["answered"] * 5)
    verdicts = parse_judge_reply(reply, requests)
    rows = judged_checklist(requests, no_material, verdicts)
    r5 = next(row for row in rows if row.request_id == "R5")
    assert r5.coverage == Coverage.NOT_PROVIDED
    assert "overridden" in r5.reason
