"""The export-side citation reader: nothing it recovers may quietly vanish."""
from engine.citations_from_export import (
    cited_sections_from_export,
    missing_citation_failures,
)
from engine.model import Match, Request
from engine.verify_citations import find_citation_failures


def a_request(request_id: str, title: str = "Specialty occupation") -> Request:
    return Request(id=request_id, title=title, text="Provide evidence.")


def a_match(
    request_id: str, file: str = "01-petition.md", heading: str = "Duties"
) -> Match:
    return Match(
        request_id=request_id, file=file, heading=heading, excerpt="x", score=1.0
    )


SECTION = """## Response to Request 1 — Specialty occupation

**Petition material relied on:**

- From `01-petition.md`, section "Duties":
  "the beneficiary designs distributed systems"

**Response:**

Prose.
"""


def test_a_multiline_rewrapped_quote_is_checked_in_full():
    rewrapped = SECTION.replace(
        '  "the beneficiary designs distributed systems"',
        '  "the beneficiary designs distributed systems\n  and mentors junior staff"',
    )
    sources = {
        "01-petition.md": "the beneficiary designs distributed systems and mentors staff"
    }
    failures = find_citation_failures(
        cited_sections_from_export(rewrapped), sources
    )
    assert any("Response to Request 1" in failure for failure in failures)


def test_a_reworded_citation_line_is_reported_as_removed():
    reworded = SECTION.replace("- From `01-petition.md`,", "- Based on `01-petition.md`,")
    cited = cited_sections_from_export(reworded)
    failures = missing_citation_failures(
        cited, [a_request("R1")], {"R1": [a_match("R1")]}
    )
    assert any("R1" in failure and "removed" in failure for failure in failures)


TWO_CITATIONS = """## Response to Request 1 — Specialty occupation

**Petition material relied on:**

- From `01-petition.md`, section "Duties":
  "the beneficiary designs distributed systems"
- From `02-letter.md`, section "Wage":
  "the offered wage is $145,000 a year"

**Response:**

Prose.
"""

TWO_MATCHES = [a_match("R1"), a_match("R1", file="02-letter.md", heading="Wage")]


def test_a_citation_the_export_dropped_is_named_by_file_and_section():
    failures = missing_citation_failures(
        cited_sections_from_export(SECTION), [a_request("R1")], {"R1": TWO_MATCHES}
    )
    assert failures == [
        "R1's section lost its citation to 02-letter.md, section \"Wage\" — "
        "a citation was removed or replaced during editing"
    ]


def test_a_citation_replaced_by_a_copy_of_another_is_caught_though_the_count_holds():
    duplicated = TWO_CITATIONS.replace(
        '- From `02-letter.md`, section "Wage":\n'
        '  "the offered wage is $145,000 a year"',
        '- From `01-petition.md`, section "Duties":\n'
        '  "the beneficiary designs distributed systems"',
    )
    cited = cited_sections_from_export(duplicated)
    assert len(cited) == 2

    failures = missing_citation_failures(cited, [a_request("R1")], {"R1": TWO_MATCHES})

    assert len(failures) == 1
    assert '02-letter.md, section "Wage"' in failures[0]


def test_an_untouched_two_citation_section_reports_nothing_missing():
    failures = missing_citation_failures(
        cited_sections_from_export(TWO_CITATIONS),
        [a_request("R1")],
        {"R1": TWO_MATCHES},
    )
    assert failures == []


def test_request_numbers_do_not_match_by_prefix():
    requests = [a_request("R1"), a_request("R10", title="Wage level")]
    matches = {"R1": [a_match("R1")], "R10": [a_match("R10")]}
    failures = missing_citation_failures(
        cited_sections_from_export(SECTION), requests, matches
    )
    assert not any("R1'" in failure for failure in failures)
    assert any("R10" in failure for failure in failures)


def test_a_complete_section_reports_nothing_missing():
    failures = missing_citation_failures(
        cited_sections_from_export(SECTION), [a_request("R1")], {"R1": [a_match("R1")]}
    )
    assert failures == []
