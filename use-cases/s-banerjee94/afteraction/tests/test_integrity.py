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
    document = "## 1. Event Overview\n\n### Observed\n\nThe squall reached Asansol [TEL-0003].\n"
    assert unfilled(document, ["1. Event Overview"]) == []


def test_a_placeholder_in_a_later_section_is_not_blamed_on_an_earlier_one():
    document = '## 1. Event Overview\n\nDrafted prose [TEL-0003].\n\n## 2. Timeline of Events\n\nPlaceholder for observed statements in it.\n'
    assert unfilled(document, ["1. Event Overview", "2. Timeline of Events"]) == [
        "2. Timeline of Events"
    ]


# ------------------------------------------------------------------ table headers


def test_a_table_header_row_is_not_scored_as_a_claim():
    """`| Time | Event |` asserts nothing and cites nothing."""
    facts = build_facts(load_corpus("storm-a"))
    table = "| Time | Event |\n| --- | --- |\n| 16:52 | First outages recorded [TEL-0004]. |"
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
    backend = MockSuperDocs(stall="6. Consumer Communications")
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


def test_a_chart_that_did_not_land_is_retried_and_lands(store, tmp_path):
    """The live failure: the curve edit strayed into the neighbouring section, section 7
    kept its placeholder, and the run failed on surgical while nothing mentioned the
    missing chart. The chart sections were outside both the placeholder sweep and the
    retry because they are not in SECTION_TITLES."""
    backend = MockSuperDocs(stall="7. Restoration Curve")
    result = _run("storm-a", store, tmp_path, backend=backend)

    assert result.retried == ["Restoration Curve"]
    assert result.ok
    assert "Placeholder for the restoration curve" not in result.exports["markdown"].read_text(
        encoding="utf-8"
    )


def test_a_contacts_chart_that_did_not_land_is_retried_and_lands(store, tmp_path):
    """Both chart sections, not just the first one."""
    backend = MockSuperDocs(stall="8. Consumer Contacts")
    result = _run("storm-a", store, tmp_path, backend=backend)

    assert result.retried == ["Consumer Contacts"]
    assert result.ok


def test_a_chart_placeholder_surviving_the_retry_is_reported(store, tmp_path):
    """Bounded at one pass here too: a chart that fails twice fails the run rather than
    exporting a report with a placeholder where the reader expects a picture."""

    class CurveNeverLands(MockSuperDocs):
        def chat(self, session_id, message, **kwargs):
            # the curve's alt text, which no other instruction carries — matching on
            # "restoration curve" also caught the timeline and lessons briefs
            if "Restoration curve for " in message:
                return {"response": "no change"}
            return super().chat(session_id, message, **kwargs)

    result = _run("storm-a", store, tmp_path, backend=CurveNeverLands())

    assert result.retried == ["Restoration Curve"]
    assert not result.ok
    assert any("Restoration Curve" in d for d in result.drift)


def test_a_chart_that_lands_first_time_is_not_retried(store, tmp_path):
    """The sweep must not re-issue a section that is already written — a second chart
    turn is a second billable operation for a picture that is already in the document."""
    result = _run("storm-a", store, tmp_path)

    assert result.retried == []
    assert result.ok


def test_verify_never_cuts_a_citation_off():
    """`verify` truncated every claim at 140 characters, which removed the citation from
    17 of storm-a's 22 claims — the one thing the command exists to show, and the thing
    the demo narration claims is on screen."""
    from typer.testing import CliRunner
    from afteraction.cli import app

    out = CliRunner().invoke(app, ["verify", "storm-a"]).output
    facts = build_facts(load_corpus("storm-a"))

    for claim in facts.claims:
        tail = claim.rendered().rsplit(" ", 1)[-1]     # the closing citation or marker
        assert tail in out, f"{tail} never reached the screen"
    assert "..." not in out


# ------------------------------------------------------------------ surgical precision


def test_fingerprints_ignore_layout_but_not_words():
    """Blank lines are how the exporter breathes; words are what the document says."""
    a = fingerprints("## 1. A\n\nSome prose [TEL-0001].\n")
    b = fingerprints("## 1. A\nSome prose [TEL-0001].\n\n\n")
    c = fingerprints("## 1. A\n\nSome other prose [TEL-0001].\n")
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
    document = "## 2. Timeline of Events\n\n### Observed\n\n**Observed**\n\n* A thing [TEL-0001]\n"
    problems = structural_drift(document, EXPECTED, [])
    assert problems == ["section label repeated as body text: Observed"]


def test_an_echoed_label_is_not_scored_as_a_claim():
    facts = build_facts(load_corpus("storm-a"))
    report = verify("**Observed**\n\n* The squall reached Asansol [TEL-0003].", facts, "timeline")
    assert report.clean
    assert report.checked == 1


def test_every_section_is_named_to_the_model_exactly_as_its_heading_reads():
    """"Restoration Curve" and "Restoration Performance" are one word apart. An
    instruction naming only the former put the chart into the latter on a live run,
    overwriting its figures. The number is what makes each name unambiguous."""
    from afteraction.sections import (
        complaints_instruction,
        curve_instruction,
        heading_for,
        instruction_for,
    )

    facts = build_facts(load_corpus("storm-a"))
    assert heading_for("curve") == "7. Restoration Curve"
    assert heading_for("restoration_performance") == "5. Restoration Performance"

    assert "“5. Restoration Performance”" in instruction_for(facts, "restoration_performance")
    assert "“7. Restoration Curve”" in curve_instruction("https://x/i.png", facts)

    # The two charts are one word apart from each other as well, and the contacts chart
    # only exists on events that have contacts — so its number is derived, not fixed.
    assert heading_for("complaints") == "8. Consumer Contacts"
    assert "“8. Consumer Contacts”" in complaints_instruction("https://x/i.png", facts)


def test_no_two_placeholders_in_the_skeleton_are_identical():
    """Five paragraphs reading the same thing gave the service five equally good answers
    to "replace the placeholder", and live edits landed in the wrong section."""
    from afteraction.sections import skeleton_html

    skeleton = skeleton_html(build_facts(load_corpus("storm-a")), [])
    found = re.findall(r">(Placeholder for [^<]+)<", skeleton)
    assert found
    assert len(found) == len(set(found)), f"duplicated placeholder text: {found}"


# ------------------------------------------------------------------ any number of events


def _event_folder(root, name, started, log_id="TEL-0001"):
    """A minimal but valid event on disk, matching the real six-file schema."""
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
                "substation": "Test 33/11 kV",
                "consumers_served": 1000,
                "started_at": f"{started}T00:00:00",
                "ended_at": f"{started}T12:00:00",
                "previous_event_id": None,
            }
        ),
        encoding="utf-8",
    )
    write(
        "weather.csv",
        [
            "entry_id,at,kind,note,issued_by",
            f"WEA-0001,{started}T00:30:00,warning,Thunderstorm warning issued.,Met office",
        ],
    )
    write(
        "telemetry.csv",
        [
            "entry_id,at,category,device,feeder,consumers_out,note,flag",
            f"{log_id},{started}T01:00:00,outage,RTU-01,F-01,100,First outages recorded.,",
            f"TEL-0002,{started}T06:00:00,restoration,RTU-01,F-01,0,All supply restored.,",
        ],
    )
    write(
        "damage.csv",
        [
            "entry_id,reported_at,asset_type,count,status,reported_by,feeder,location,note,"
            "source_ref,confirmed_at,repaired_at",
            f"DMG-0001,{started}T01:20:00,pole,1,repaired,telemetry,F-01,Depot Road,"
            f"Pole snapped.,{log_id},{started}T01:40:00,{started}T05:30:00",
        ],
    )
    write(
        "crew.csv",
        [
            "entry_id,crew_type,home_base,headcount,assigned_to,mobilized_at,released_at,"
            "mutual_aid,note,sources",
            f"CRW-0001,line gang,Depot,4,F-01,{started}T01:30:00,{started}T06:00:00,false,,{log_id}",
        ],
    )
    write(
        "comms.csv",
        [
            "entry_id,at,direction,channel,audience,subject,note,resolved_at,sources",
            f"COM-0001,{started}T01:45:00,in,call centre,20,Supply failure reported,,"
            f"{started}T05:00:00,{log_id}",
            f"COM-0002,{started}T02:00:00,out,SMS,100,Supply interruption acknowledged,,,{log_id}",
        ],
    )
    write(
        "field_reports.csv",
        [
            "entry_id,at,category,location,feeder,note,reported_by",
            f"FLD-0001,{started}T05:45:00,safety,Depot Road,F-01,Site cleared and released.,Supervisor",
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
            f'LL-{n},"Item {n}","Owner {n}","Detail for item {n}.",TEL-0001\n',
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


# ------------------------------------------------------ an event that raised nothing

# These use a synthetic event rather than a committed one: an event with no lessons files
# and no mutual aid is a *case*, not a dataset, and the suite must not depend on a folder
# that may or may not be on disk.


def _quiet_event(tmp_path, name="quiet-storm"):
    """An event with no lessons files at all and no mutual-aid crews."""
    root = tmp_path / "data"
    _event_folder(root, name, "2026-05-01")
    (root / name / "lessons_opened.csv").unlink()
    (root / name / "lesson_resolutions.csv").unlink()
    return root, name


def test_missing_lessons_files_mean_no_lessons_not_an_error(tmp_path):
    root, name = _quiet_event(tmp_path)
    result = run_event(
        name, MockSuperDocs(), data_root=root,
        store_path=tmp_path / "l.json", out_dir=tmp_path / "out",
    )
    assert result.ok
    assert result.carry["raised_here"] == 0


def test_an_event_that_raised_nothing_states_the_absence(tmp_path):
    """Leaving the placeholder there shipped the word "Placeholder" in a report that
    reported ok, because no edit was ever going to arrive for a section with nothing
    to say."""
    from afteraction.sections import skeleton_html

    root, name = _quiet_event(tmp_path)
    skeleton = skeleton_html(build_facts(load_corpus(name, root)), [], [])

    assert "No new lessons-learned items were raised by this event." in skeleton
    assert "Placeholder for items raised" not in skeleton


def test_an_event_that_raised_something_keeps_the_placeholder_for_its_edit(tmp_path):
    from afteraction.lessons import load_store
    from afteraction.sections import skeleton_html

    store = tmp_path / "l.json"
    run_event("storm-a", MockSuperDocs(), store_path=store, out_dir=tmp_path / "a")
    raised = load_store(store)

    skeleton = skeleton_html(build_facts(load_corpus("storm-a")), [], raised)
    assert "Placeholder for items raised" in skeleton


def test_an_event_with_no_lessons_ships_no_placeholder(tmp_path):
    root, name = _quiet_event(tmp_path)
    result = run_event(
        name, MockSuperDocs(), data_root=root,
        store_path=tmp_path / "l.json", out_dir=tmp_path / "out",
    )
    assert result.drift == []
    assert "Placeholder" not in result.exports["markdown"].read_text(encoding="utf-8")


def test_the_lessons_section_is_covered_by_the_drift_check():
    """It is the one section whose content can be legitimately absent, which is exactly
    why a surviving placeholder there went unnoticed on a live run."""
    document = '## 7. Lessons Learned\n\n### Raised by this event\n\nPlaceholder for items raised by this event.\n'
    assert unfilled(document, ["7. Lessons Learned"]) == ["7. Lessons Learned"]


def test_mutual_aid_is_only_judged_when_mutual_aid_happened(tmp_path):
    """An event handled with its own gangs has nothing to say here. Asserting that aid
    "was requested at an appropriate point" when none was requested is a false statement
    about something that never happened — marked [assessed], but still false."""
    from afteraction.facts import MOBILISATION
    from afteraction.models import Kind

    def assessed(event, root=None):
        facts = build_facts(load_corpus(event, root))
        return [c.text for c in facts.for_section(MOBILISATION) if c.kind is Kind.ASSESSED]

    root, name = _quiet_event(tmp_path)
    assert any("Mutual aid" in c for c in assessed("storm-a"))  # storm-a called for aid
    assert assessed(name, root) == []                           # this one did not


def test_a_repeated_label_is_recognised_in_any_styling():
    """A live run repeated the same label twice in one document — once as
    "**What the records do not show**" and once as a bare "Assessed". Insisting on the
    asterisks caught the first and scored the second as an unsourced claim."""
    from afteraction.trace import _ECHOED_LABEL

    for styling in ("Observed", "**Observed**", "*Observed*", "_Observed_", "Observed:"):
        assert _ECHOED_LABEL.match(styling), styling
    assert not _ECHOED_LABEL.match("Observed outages began at 16:52 [TEL-0004].")


def test_a_plain_repeated_label_is_not_scored_as_a_claim():
    facts = build_facts(load_corpus("storm-a"))
    report = verify('Assessed\n\nThe squall reached Asansol [TEL-0003].', facts, "timeline")
    assert report.clean
    assert report.checked == 1


def test_instruction_labels_never_reuse_a_heading_word():
    """The label and the heading were the same string — "WHAT THE RECORDS DO NOT SHOW" was
    the heading, verbatim — and the model copied the label into the document underneath the
    heading it already had. Two live runs in a row. A label that shares no wording with a
    heading gives it nothing to copy."""
    from afteraction.facts import SECTION_TITLES
    from afteraction.sections import instruction_for

    headings = {"observed", "assessed", "what the records do not show", "raised by this event"}
    facts = build_facts(load_corpus("storm-a"))

    for key in SECTION_TITLES:
        text = instruction_for(facts, key) or ""
        for line in text.splitlines():
            stripped = line.strip()
            # the capitalised label that opens each block
            if stripped[:3].isupper() and " — " in stripped:
                label = stripped.split(" — ")[0].strip().casefold()
                assert label not in headings, f"{key}: label {label!r} is a heading"


# ------------------------------------------------------------------ time windows


def test_the_window_size_follows_the_events_length():
    """The rule, stated once so it can be defended: an event that ran longer than
    sixteen hours gets two-hour bullets, a shorter one gets hourly bullets."""
    from afteraction.windows import LONG_EVENT_HOURS, window_hours

    assert window_hours(LONG_EVENT_HOURS) == 1
    assert window_hours(LONG_EVENT_HOURS + 0.5) == 2
    assert window_hours(0.5) == 1
    assert window_hours(200) == 2


def test_both_storms_exercise_a_different_window_size():
    """Storm A runs 45 hours and Storm B runs 12, so the pair covers both branches of
    the rule rather than only the one the first event happens to take."""
    from afteraction.windows import window_hours

    a = load_corpus("storm-a")
    b = load_corpus("storm-b")
    assert window_hours(a.event.duration_hours) == 2
    assert window_hours(b.event.duration_hours) == 1


def test_windows_are_clock_aligned_and_empty_ones_are_dropped():
    """"18:00–20:00" is what a reader expects; "17:43–19:43" is what anchoring to the
    event's start minute would give. A quiet night produces no bullets at all."""
    from afteraction.windows import build_windows

    corpus = load_corpus("storm-a")
    windows = build_windows(corpus)
    assert windows
    for w in windows:
        assert w.start.minute == 0 and w.start.second == 0
        assert w.start.hour % 2 == 0  # two-hour windows on this event
        assert w.entries  # never an empty bullet


def test_every_timeline_record_lands_in_exactly_one_window():
    """A record dropped between windows is a record that vanished from the report, and
    one counted twice is a claim the document makes about itself."""
    from afteraction.windows import TIMELINE_CATEGORIES, build_windows

    corpus = load_corpus("storm-a")
    windows = build_windows(corpus)
    placed = [rid for w in windows for rid in w.sources]
    expected = [e.entry_id for e in corpus.log if e.category in set(TIMELINE_CATEGORIES)]

    assert len(placed) == len(set(placed)), "a record was placed in two windows"
    assert set(placed) == set(expected)


def test_the_timeline_compresses_rather_than_growing_with_the_log():
    """The whole reason windows exist. Forty-five records must not produce forty-five
    bullets, because a real substation log runs to thousands."""
    facts = build_facts(load_corpus("storm-a"))
    records = sum(len(w.entries) for w in facts.windows)
    assert records > 40
    assert len(facts.windows) < records / 2


def test_all_the_windows_go_out_in_one_instruction(store, tmp_path):
    """One request, not one per window.

    A forty-five hour event is seventeen windows. Seventeen requests would be seventeen
    billable operations for a section that costs one, so the batching is a budget
    property and is checked as one.
    """
    backend = MockSuperDocs()
    result = run_event("storm-a", backend, store_path=store, out_dir=tmp_path / "a")

    timeline_calls = [m for m in backend.instructions if "TIME WINDOWS" in m]
    assert len(timeline_calls) == 1
    for window in result.facts.windows:
        assert window.label in timeline_calls[0]


def test_a_windowed_bullet_carries_every_record_it_stands_for(store, tmp_path):
    """A bullet standing for fifteen records has to cite all fifteen. Dropping one is
    how a summary quietly becomes an assertion nobody can check."""
    result = _run("storm-a", store, tmp_path)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    timeline = markdown.split("2. Timeline of Events", 1)[1].split("## 3.", 1)[0]

    for window in result.facts.windows:
        for rid in window.sources:
            assert rid in timeline, f"{rid} was dropped from the timeline"


# ------------------------------------------------------------------ executive summary


def test_the_summary_is_written_last(store, tmp_path):
    """A summary written before the sections is a summary of what they were going to
    say. It has to be the final edit, after even the retries."""
    backend = MockSuperDocs()
    run_event("storm-a", backend, store_path=store, out_dir=tmp_path / "a")

    summaries = [i for i, m in enumerate(backend.instructions) if "executive summary" in m.lower()]
    assert summaries
    assert summaries[-1] == len(backend.instructions) - 1


def test_the_summary_placeholder_never_survives(store, tmp_path):
    """It sits at the very top of the document, so a summary that quietly failed to
    land is the first thing a reader sees."""
    from afteraction.sections import SUMMARY_PLACEHOLDER

    result = _run("storm-a", store, tmp_path)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    assert "Executive Summary" in markdown
    assert SUMMARY_PLACEHOLDER not in markdown


def test_the_summary_asks_the_model_to_read_the_document_not_a_second_copy_of_the_facts():
    """It is the one instruction that works off the document. Handing over the facts
    again would give the summary and the body a chance to disagree."""
    from afteraction.sections import summary_instruction

    facts = build_facts(load_corpus("storm-a"))
    text = summary_instruction(facts)
    assert "already written in the sections" in text
    assert "Do not carry citations into the summary" in text
    # no record ids are supplied: there is nothing to copy from
    assert not re.search(r"\b(WEA|TEL|DMG|CRW|COM|FLD)-\d{4}\b", text)
