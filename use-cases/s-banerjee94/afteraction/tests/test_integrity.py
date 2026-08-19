"""The document's shape, not only its citations.

Checking that every claim cites a real log entry says nothing about content the model
invented *outside* the sections being checked, and nothing about an edit that reported
success and changed nothing. Both happened on live runs, and both looked like a clean
100% result at the time. These are the checks that close that gap.
"""

from __future__ import annotations

import re

import pytest

from afteraction.corpus import load_corpus
from afteraction.facts import build_facts
from afteraction.mock import MockSuperDocs
from afteraction.pipeline import expected_headings, run_event
from afteraction.surgical import SurgicalReport, fingerprints, moved
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
    backend = MockSuperDocs(stall="5. Consumer Communications")
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


# ------------------------------------------------------------------ surgical precision


def test_fingerprints_ignore_layout_but_not_words():
    """Blank lines are how the exporter breathes; words are what the document says."""
    a = fingerprints("## 1. A\n\nSome prose [EL-0001].\n")
    b = fingerprints("## 1. A\nSome prose [EL-0001].\n\n\n")
    c = fingerprints("## 1. A\n\nSome other prose [EL-0001].\n")
    assert a == b
    assert a != c


def test_fingerprints_ignore_a_regenerated_image_signature():
    """A hosted image comes back with a fresh pre-signed URL on every export. That is a
    credential, not content, and comparing it would flag the curve on every turn."""
    a = fingerprints("## 6. Restoration Curve\n\n![curve](https://x/i.png?X-Goog-Signature=aaa)\n")
    b = fingerprints("## 6. Restoration Curve\n\n![curve](https://x/i.png?X-Goog-Signature=zzz)\n")
    assert a == b


def test_fingerprints_do_not_ignore_a_different_image():
    a = fingerprints("## 6. Restoration Curve\n\n![curve](https://x/one.png?sig=a)\n")
    b = fingerprints("## 6. Restoration Curve\n\n![curve](https://x/two.png?sig=a)\n")
    assert a != b


def test_an_edit_confined_to_its_section_passes():
    before = {"1. A": "aaa", "2. B": "bbb"}
    after = {"1. A": "changed", "2. B": "bbb"}
    report = SurgicalReport()
    assert report.record("1. A", before, after) == []
    assert report.clean


def test_an_edit_that_moves_another_section_is_reported():
    before = {"1. A": "aaa", "2. B": "bbb"}
    after = {"1. A": "changed", "2. B": "also changed"}
    report = SurgicalReport()
    assert report.record("1. A", before, after) == ["2. B"]
    assert not report.clean
    assert "2. B" in report.collateral[0]


def test_a_section_that_disappears_counts_as_moved():
    """Deleting a section is a change to it, not an absence of one."""
    assert moved({"1. A": "aaa", "2. B": "bbb"}, {"1. A": "aaa"}) == {"2. B"}


def test_a_run_whose_edit_strays_is_reported_as_failed(store, tmp_path):
    """The whole point: an instruction says "change nothing outside this section", and a
    run that breaks that promise must not print ok."""

    class Sloppy(MockSuperDocs):
        """Writes a stray line into the timeline no matter which section was asked for."""

        def chat(self, session_id, message, **kwargs):
            result = super().chat(session_id, message, **kwargs)
            if "Event Overview" in message:
                html = self.documents[session_id]
                self.documents[session_id] = html.replace(
                    "Placeholder for observed statements in 2. Timeline of Events.",
                    "Something nobody asked for.",
                )
            return result

    result = _run("storm-a", store, tmp_path, backend=Sloppy())

    assert not result.surgical.clean
    assert not result.ok
    assert any("Timeline of Events" in c for c in result.surgical.collateral)


def test_a_section_label_echoed_as_bold_body_text_is_reported():
    """A live run wrote "**Observed**" as a paragraph under the real Observed heading.
    Scoring it as a claim reported an unsourced assertion, which explained nothing."""
    document = "## 2. Timeline of Events\n\n### Observed\n\n**Observed**\n\n* A thing [EL-0001]\n"
    problems = structural_drift(document, EXPECTED, [])
    assert problems == ["section label repeated as body text: Observed"]


def test_an_echoed_label_is_not_scored_as_a_claim():
    facts = build_facts(load_corpus("storm-a"))
    report = verify("**Observed**\n\n* The squall reached Asansol [EL-0003].", facts, "timeline")
    assert report.clean
    assert report.checked == 1


def test_every_section_is_named_to_the_model_exactly_as_its_heading_reads():
    """"Restoration Curve" and "Restoration Performance" are one word apart. An
    instruction naming only the former put the chart into the latter on a live run,
    overwriting its figures. The number is what makes each name unambiguous."""
    from afteraction.sections import curve_instruction, heading_for, instruction_for

    facts = build_facts(load_corpus("storm-a"))
    assert heading_for("curve") == "6. Restoration Curve"
    assert heading_for("restoration_performance") == "4. Restoration Performance"

    assert "“4. Restoration Performance”" in instruction_for(facts, "restoration_performance")
    assert "“6. Restoration Curve”" in curve_instruction("https://x/i.png", facts)


def test_no_two_placeholders_in_the_skeleton_are_identical():
    """Five paragraphs reading the same thing gave the service five equally good answers
    to "replace the placeholder", and live edits landed in the wrong section."""
    from afteraction.sections import skeleton_html

    skeleton = skeleton_html(build_facts(load_corpus("storm-a")), [])
    found = re.findall(r">(Placeholder for [^<]+)<", skeleton)
    assert found
    assert len(found) == len(set(found)), f"duplicated placeholder text: {found}"
