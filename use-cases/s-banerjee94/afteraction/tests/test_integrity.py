"""The document's shape, not only its citations.

Checking that every claim cites a real log entry says nothing about content the model
invented *outside* the sections being checked, and nothing about an edit that reported
success and changed nothing. Both happened on live runs, and both looked like a clean
100% result at the time. These are the checks that close that gap.
"""

from __future__ import annotations

import pytest

from afteraction.corpus import load_corpus
from afteraction.facts import build_facts
from afteraction.mock import MockSuperDocs
from afteraction.pipeline import expected_headings, run_event
from afteraction.trace import structural_drift, strip_table_headers, unfilled, verify

EXPECTED = expected_headings([])


@pytest.fixture
def store(tmp_path):
    return tmp_path / "lessons.json"


def _run(event, store, tmp_path, **kwargs):
    backend = kwargs.pop("backend", None) or MockSuperDocs()
    return run_event(event, backend, store_path=store, out_dir=tmp_path / event, **kwargs)


# ------------------------------------------------------------------ invented content


def test_a_heading_the_skeleton_never_wrote_is_reported():
    """A live run added a duplicate section heading and a "Please fill" line, and every
    claim under the real headings still traced. Nothing looked at the new heading."""
    document = "# Storm Restoration After-Action Report\n\n## 1. Event Overview\n\n## Appendix\n"
    assert structural_drift(document, EXPECTED, []) == ["unexpected heading: Appendix"]


def test_the_skeletons_own_headings_are_not_reported():
    document = "\n".join(f"## {h}" for h in EXPECTED)
    assert structural_drift(document, EXPECTED, []) == []


def test_the_carry_forward_heading_is_only_expected_when_something_carried():
    assert "Carried forward from previous events" not in expected_headings([])


def test_a_surviving_placeholder_is_reported():
    document = "## 1. Event Overview\n\n### Observed\n\nPlaceholder for observed statements.\n"
    assert unfilled(document, ["1. Event Overview"]) == ["1. Event Overview"]


def test_a_drafted_section_is_not_reported():
    document = "## 1. Event Overview\n\n### Observed\n\nThe squall reached Asansol [EL-0003].\n"
    assert unfilled(document, ["1. Event Overview"]) == []


def test_a_placeholder_in_a_later_section_is_not_blamed_on_an_earlier_one():
    document = (
        "## 1. Event Overview\n\nDrafted prose [EL-0003].\n\n"
        "## 2. Timeline of Events\n\nPlaceholder for observed statements.\n"
    )
    assert unfilled(document, ["1. Event Overview", "2. Timeline of Events"]) == [
        "2. Timeline of Events"
    ]


# ------------------------------------------------------------------ table headers


def test_a_table_header_row_is_not_scored_as_a_claim():
    """`| Time | Event |` asserts nothing and cites nothing."""
    facts = build_facts(load_corpus("storm-a"))
    table = "| Time | Event |\n| --- | --- |\n| 16:52 | First outages recorded [EL-0004]. |"
    report = verify(table, facts, "timeline")
    assert report.clean
    assert report.checked == 1


def test_stripping_headers_leaves_the_body_rows():
    text = "| A | B |\n| --- | --- |\n| one | two |"
    assert strip_table_headers(text).strip() == "| one | two |"


# ------------------------------------------------------------------ the retry


def test_an_edit_that_silently_did_nothing_is_retried_and_lands(store, tmp_path):
    """The failure this exists for: the service reported the change applied, the section
    kept its placeholder, and the run reported success."""
    backend = MockSuperDocs(stall="Consumer Communications")
    result = _run("storm-a", store, tmp_path, backend=backend)

    assert result.retried == ["Consumer Communications"]
    assert result.ok
    assert result.drift == []
    assert "Placeholder" not in result.exports["markdown"].read_text(encoding="utf-8")


def test_a_section_a_person_rejected_is_not_retried(store, tmp_path):
    """A refusal is a decision the gate exists to record. Re-issuing it would overturn
    that decision silently, which is worse than an empty section."""
    seen: list[str] = []

    def gate(change):
        seen.append(change.change_id)
        return (len(seen) != 1), "first one rejected"

    result = _run("storm-a", store, tmp_path, approver=gate)

    assert result.retried == []
    assert "Placeholder" in result.exports["markdown"].read_text(encoding="utf-8")


def test_the_retry_is_bounded_to_one_pass(store, tmp_path):
    """A section that fails twice is reported, never retried in a loop."""

    class NeverLands(MockSuperDocs):
        def chat(self, session_id, message, **kwargs):
            if "Consumer Communications" in message:
                return {"response": "no change"}
            return super().chat(session_id, message, **kwargs)

    result = _run("storm-a", store, tmp_path, backend=NeverLands())

    assert result.retried == ["Consumer Communications"]
    assert not result.ok  # reported, not looped
    assert any("Consumer Communications" in d for d in result.drift)
