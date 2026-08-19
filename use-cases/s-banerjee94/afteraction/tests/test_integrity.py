"""The document's shape, not only its citations.

Checking that every claim cites a real log entry says nothing about content the model
invented *outside* the sections being checked, and nothing about an edit that reported
success and changed nothing. Both happened on live runs, and both looked like a clean
100% result at the time. These are the checks that close that gap.
"""

from __future__ import annotations

import json
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


# ------------------------------------------------------------------ any number of events


def _event_folder(root, name, started, log_id="EL-0001"):
    """A minimal but valid event on disk, matching the real CSV schema."""
    d = root / name
    d.mkdir(parents=True)
    nl = chr(10)

    def write(filename, rows):
        (d / filename).write_text(nl.join(rows) + nl, encoding="utf-8")

    (d / "event.json").write_text(
        json.dumps(
            {
                "event_id": name,
                "name": f"Storm {name}",
                "utility": "Test Power",
                "consumers_served": 1000,
                "started_at": f"{started}T00:00:00",
                "ended_at": f"{started}T12:00:00",
                "previous_event_id": None,
            }
        ),
        encoding="utf-8",
    )
    write(
        "event_log.csv",
        [
            "entry_id,at,category,feeder,consumers_out,note,flag",
            f"{log_id},{started}T01:00:00,outage,F-01,100,First outages recorded.,",
            f"EL-0002,{started}T06:00:00,restoration,F-01,0,All supply restored.,",
        ],
    )
    write(
        "crew_records.csv",
        [
            "crew_id,crew_type,home_base,headcount,mobilized_at,released_at,mutual_aid,sources",
            f"CR-01,line,Depot,4,{started}T01:30:00,{started}T06:00:00,false,{log_id}",
        ],
    )
    write(
        "customer_comms.csv",
        [
            "comm_id,sent_at,channel,audience,subject,sources",
            f"CC-01,{started}T02:00:00,SMS,100,Supply interruption acknowledged,{log_id}",
        ],
    )
    write("lessons_opened.csv", ["lesson_id,title,owner,detail,sources"])
    write("lesson_resolutions.csv", ["lesson_id,status,note,sources"])
    return d


def test_no_events_on_disk_is_reported_not_crashed(tmp_path):
    from afteraction.corpus import available_events, events_in_order

    empty = tmp_path / "data"
    empty.mkdir()
    assert available_events(empty) == []
    assert events_in_order(empty) == []


def test_a_missing_data_folder_is_empty_not_an_error(tmp_path):
    from afteraction.corpus import available_events

    assert available_events(tmp_path / "nothing-here") == []


def test_one_event_is_a_valid_corpus(tmp_path):
    from afteraction.corpus import events_in_order

    root = tmp_path / "data"
    _event_folder(root, "only-storm", "2026-01-01")
    assert events_in_order(root) == ["only-storm"]


def test_events_are_ordered_by_date_not_by_folder_name(tmp_path):
    """A folder name is a naming convention; the start date is a fact about the weather.
    Carry-forward only means anything in chronological order."""
    from afteraction.corpus import available_events, events_in_order

    root = tmp_path / "data"
    _event_folder(root, "zulu-storm", "2026-01-01")   # first by date, last by name
    _event_folder(root, "alpha-storm", "2026-06-01")  # last by date, first by name

    assert available_events(root) == ["alpha-storm", "zulu-storm"]  # alphabetical
    assert events_in_order(root) == ["zulu-storm", "alpha-storm"]   # chronological


def test_three_events_all_run_and_the_register_accumulates(tmp_path):
    """Nothing in the pipeline assumes exactly two storms."""
    from afteraction.corpus import events_in_order
    from afteraction.lessons import load_store

    root = tmp_path / "data"
    for n, date in enumerate(("2026-01-01", "2026-02-01", "2026-03-01"), start=1):
        d = _event_folder(root, f"storm-{n}", date)
        (d / "lessons_opened.csv").write_text(
            "lesson_id,title,owner,detail,sources\n"
            f'LL-{n},"Item {n}","Owner {n}","Detail for item {n}.",EL-0001\n',
            encoding="utf-8",
        )

    order = events_in_order(root)
    assert order == ["storm-1", "storm-2", "storm-3"]

    store = tmp_path / "lessons.json"
    inherited_counts = []
    for event in order:
        result = run_event(
            event,
            MockSuperDocs(),
            data_root=root,
            store_path=store,
            out_dir=tmp_path / "out" / event,
        )
        inherited_counts.append(result.carry["inherited"])

    assert inherited_counts == [0, 1, 2]      # each report inherits everything before it
    assert len(load_store(store)) == 3
