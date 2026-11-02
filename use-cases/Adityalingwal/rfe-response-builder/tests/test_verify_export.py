import re

import pytest

from engine.coverage_checklist import build_checklist
from engine.model import ChecklistRow, Coverage, Request
from engine.requests_from_notice import parse_notice
from engine.response_skeleton import build_skeleton
from engine.retrieve_petition_material import retrieve
from engine.verify_export import response_slices, verify_export

PARTIAL_GAP = (
    "**Evidence gap:** the petition only touches this point in general "
    "terms. New evidence is needed — needs attorney confirmation."
)
NOT_PROVIDED_GAP = (
    "**Evidence gap:** the petition contains no material addressing this "
    "request. The required evidence is not provided — needs attorney "
    "confirmation before this section can be completed."
)


@pytest.fixture(scope="module")
def corpus(notice_text, sections, retrieval_config):
    requests = parse_notice(notice_text)
    matches = retrieve(requests, sections, retrieval_config)
    checklist = build_checklist(requests, matches, retrieval_config)
    return requests, checklist


def drafted(skeleton: str) -> str:
    return re.sub(
        r"\[DRAFT RESPONSE FOR R\d+ — TO BE WRITTEN\]",
        "The petition provides the requested material.",
        skeleton,
    )


def test_a_fully_drafted_export_passes(corpus):
    requests, checklist = corpus
    export = drafted(build_skeleton(requests, checklist))
    assert verify_export(export, requests, checklist) == []


def test_a_surviving_placeholder_fails_the_run(corpus):
    requests, checklist = corpus
    export = build_skeleton(requests, checklist)
    failures = verify_export(export, requests, checklist)
    assert any("placeholder survived" in f for f in failures)


def test_a_dropped_response_section_is_named(corpus):
    requests, checklist = corpus
    export = drafted(build_skeleton(requests, checklist))
    export = export.replace("## Response to Request 5", "## Removed")
    failures = verify_export(export, requests, checklist)
    assert any("R5" in f and "missing" in f for f in failures)


def test_an_altered_officer_quote_is_caught(corpus):
    requests, checklist = corpus
    export = drafted(build_skeleton(requests, checklist))
    export = export.replace("legible copy", "unquestionable copy")
    failures = verify_export(export, requests, checklist)
    assert any("officer quote was altered" in f for f in failures)


def test_drafting_away_the_gap_language_is_caught(corpus):
    requests, checklist = corpus
    export = drafted(build_skeleton(requests, checklist))
    export = export.replace("not provided", "fully documented")
    export = export.replace("attorney confirmation", "our records")
    failures = verify_export(export, requests, checklist)
    assert failures != []


def all_answered(checklist):
    return [
        ChecklistRow(
            request_id=row.request_id,
            title=row.title,
            coverage=Coverage.ANSWERED,
            matches=row.matches,
            reason="petition material found",
        )
        for row in checklist
    ]


def test_a_gap_row_stripped_of_its_own_language_is_named_even_when_the_table_still_labels_it(
    corpus,
):
    # the coverage table always spells out "Not provided — needs attorney
    # confirmation", so a document-wide search can never notice that R5's
    # own section lost the warning
    requests, checklist = corpus
    export = drafted(build_skeleton(requests, checklist)).replace(NOT_PROVIDED_GAP, "")
    assert "not provided — needs attorney confirmation" in export.lower()

    failures = verify_export(export, requests, checklist)

    gap_failures = [f for f in failures if "evidence-gap" in f]
    assert len(gap_failures) == 1
    assert "R5" in gap_failures[0]


def test_every_row_stripped_of_its_gap_language_is_named_not_only_the_first(corpus):
    requests, checklist = corpus
    export = drafted(build_skeleton(requests, checklist))
    export = export.replace(NOT_PROVIDED_GAP, "").replace(PARTIAL_GAP, "")

    failures = verify_export(export, requests, checklist)

    gap_failures = [f for f in failures if "evidence-gap" in f]
    assert len(gap_failures) == 2
    assert {"R4", "R5"} == {f.split("'")[0] for f in gap_failures}


def test_a_partial_row_passes_on_its_own_gap_line_without_saying_not_provided(corpus):
    requests, checklist = corpus
    export = drafted(build_skeleton(requests, checklist))
    r4_section = response_slices(export)["R4"]
    assert "attorney confirmation" in r4_section
    assert "not provided" not in r4_section.lower()

    assert verify_export(export, requests, checklist) == []


def test_an_all_answered_export_passes_verification(corpus):
    requests, checklist = corpus
    answered = all_answered(checklist)
    export = drafted(build_skeleton(requests, answered))

    assert verify_export(export, requests, answered) == []


LONG_REQUEST_TEXT = " ".join(
    f"Sentence {i} of the officer's concern about the beneficiary's evidence."
    for i in range(1, 23)
)


def answered_row(request: Request) -> ChecklistRow:
    return ChecklistRow(
        request_id=request.id,
        title=request.title,
        coverage=Coverage.ANSWERED,
        reason="petition material found",
    )


def test_a_long_officer_request_is_quoted_and_verified_in_full_not_trimmed():
    assert len(LONG_REQUEST_TEXT) > 1500
    request = Request(id="R1", title="Long request", text=LONG_REQUEST_TEXT)
    checklist = [answered_row(request)]
    export = drafted(build_skeleton([request], checklist))

    assert LONG_REQUEST_TEXT in export
    assert verify_export(export, [request], checklist) == []


def test_an_officer_quote_whose_line_break_the_export_deleted_still_passes():
    request = Request(
        id="R1",
        title="Premises",
        text="Confirm the work sites: 123 Main St<br>Suite 4, Dover.",
    )
    checklist = [answered_row(request)]
    export = drafted(build_skeleton([request], checklist)).replace(
        "123 Main St<br>Suite 4", "123 Main StSuite 4"
    )

    assert verify_export(export, [request], checklist) == []


def test_a_word_changed_beyond_the_old_trim_point_is_still_caught():
    request = Request(id="R1", title="Long request", text=LONG_REQUEST_TEXT)
    checklist = [answered_row(request)]
    export = drafted(build_skeleton([request], checklist)).replace(
        "Sentence 20 of the officer's", "Sentence 20 of the attorney's"
    )

    failures = verify_export(export, [request], checklist)

    assert any("officer quote was altered" in failure for failure in failures)


def numbered_corpus(count: int):
    requests = [
        Request(id=f"R{i}", title=f"Topic {i}", text=f"Provide evidence item {i}.")
        for i in range(1, count + 1)
    ]
    return requests, [answered_row(request) for request in requests]


def test_a_missing_section_1_is_named_even_though_section_10_starts_the_same_way():
    requests, checklist = numbered_corpus(11)
    lines = drafted(build_skeleton(requests, checklist)).splitlines()
    start = next(
        i for i, line in enumerate(lines) if line.startswith("## Response to Request 1 —")
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("## "))
    del lines[start:end]

    failures = verify_export("\n".join(lines), requests, checklist)

    assert any("R1's response section is missing" in failure for failure in failures)


def test_a_gap_case_that_lost_the_phrase_from_its_own_section_still_fails(corpus):
    requests, checklist = corpus
    export = drafted(build_skeleton(requests, checklist)).replace(
        "The required evidence is not provided", "The evidence is on file"
    )

    failures = verify_export(export, requests, checklist)

    assert any("R5" in f and "evidence-gap" in f for f in failures)


def test_a_heading_line_inside_the_officer_request_does_not_split_its_section():
    # a markdown notice can carry "## ..." lines inside one request; quoted as
    # live markdown they would start a new section in the export
    text = (
        "Submit proof of the degree.\n"
        "## Supporting documents\n"
        "Include transcripts and the evaluation."
    )
    requests = [
        Request(id="R1", title="Degree", text=text),
        Request(id="R2", title="Wage", text="Submit the certified wage record."),
    ]
    checklist = [answered_row(r) for r in requests]
    export = drafted(build_skeleton(requests, checklist))

    slices = response_slices(export)
    assert set(slices) == {"R1", "R2"}
    assert "requested material" in slices["R1"]
    assert verify_export(export, requests, checklist) == []


def test_an_altered_quote_is_caught_in_its_own_section_even_when_another_section_repeats_it():
    same = "Submit the certified degree evaluation."
    requests = [
        Request(id="R1", title="First", text=same),
        Request(id="R2", title="Second", text=same),
    ]
    checklist = [answered_row(r) for r in requests]
    export = drafted(build_skeleton(requests, checklist))
    export = export.replace(same, "Submit a certified degree evaluation.", 1)

    failures = verify_export(export, requests, checklist)
    assert any(f.startswith("R1") and "officer quote was altered" in f for f in failures)
