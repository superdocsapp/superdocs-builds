"""End to end, offline: both storms, the gate, and the carry-forward across them.

Everything here runs with no key and no network. The mock is not a rubber stamp — it
can be told to draft badly, and these tests use that to prove the pipeline catches a
bad draft instead of exporting it.
"""

from __future__ import annotations

import pytest

from afteraction.mock import MockSuperDocs
from afteraction.models import LessonStatus
from afteraction.pipeline import markdown_sections, run_event


@pytest.fixture
def store(tmp_path):
    return tmp_path / "lessons.json"


def _run(event, store, tmp_path, **kwargs):
    backend = kwargs.pop("backend", None) or MockSuperDocs()
    return run_event(event, backend, store_path=store, out_dir=tmp_path / event, **kwargs)


def test_a_clean_run_traces_every_claim(store, tmp_path):
    result = _run("storm-a", store, tmp_path)
    assert result.ok
    assert result.trace.checked > 20
    assert result.trace.rate() == 100.0
    assert result.trace.flagged == []


def test_the_exported_document_is_what_gets_verified(store, tmp_path):
    """Not the instructions that were sent — the file that comes out the other end."""
    result = _run("storm-a", store, tmp_path)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    assert "Storm Restoration After-Action Report" in markdown
    assert "EL-0008" in markdown
    assert result.exports["docx"].exists()

    sections = markdown_sections(markdown)
    assert "timeline" in sections
    assert "EL-" in sections["timeline"]


def test_observed_and_assessed_stay_apart_in_the_document(store, tmp_path):
    result = _run("storm-a", store, tmp_path)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    assert "### Observed" in markdown
    assert "### Assessed" in markdown
    assert "[assessed]" in markdown
    # a judgement never carries a citation, wherever it ends up
    for line in markdown.splitlines():
        if "[assessed]" in line:
            assert "EL-" not in line.split("[assessed]")[0][-90:]


def test_gaps_reach_the_document_rather_than_being_dropped(store, tmp_path):
    result = _run("storm-a", store, tmp_path)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    assert "What the records do not show" in markdown
    assert "CR-A11" in markdown
    assert "CC-A06" in markdown
    assert "[no record]" in markdown


def test_the_curve_is_placed_inside_the_document(store, tmp_path):
    """The card asks for the diagram *inside* the document, so the export has to carry
    the actual image — not a reference to one that isn't there."""
    import base64

    backend = MockSuperDocs()
    result = _run("storm-a", store, tmp_path, backend=backend)

    assert backend.images
    url = backend.images[0]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]).startswith(b"\x89PNG")

    page = result.exports["docx"].read_text(encoding="utf-8")
    assert url in page  # the bytes really are in the exported document
    assert "Restoration curve" in result.exports["markdown"].read_text(encoding="utf-8")


def test_the_offline_export_is_named_for_what_it_actually_is(store, tmp_path):
    """The mock cannot produce Open XML, so it must not hand back a file called .docx."""
    result = _run("storm-a", store, tmp_path)
    assert result.exports["docx"].suffix == ".html"
    assert result.exports["docx"].exists()


def test_the_curve_caption_lands_without_dragging_in_its_instruction(store, tmp_path):
    """A caption delimited by typographic quotes was once matched from the straight
    quote closing alt="...", which pulled the instruction prose into the document."""
    result = _run("storm-a", store, tmp_path)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    curve = markdown.split("Restoration Curve", 1)[1].split("##", 1)[0]
    assert "Consumers without supply over the course of Kalbaisakhi Squall" in curve
    assert "Below the image" not in curve
    assert "Change nothing outside this section" not in markdown
    assert "/>" not in markdown


def test_carry_forward_citations_name_the_event_whose_log_they_mean(store, tmp_path):
    """Entry ids restart at EL-0001 each event, so a bare id in a two-storm table is
    ambiguous. The closing evidence must point at the closing event's log."""
    _run("storm-a", store, tmp_path)
    result = _run("storm-b", store, tmp_path)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    table = markdown.split("Carried forward", 1)[1].split("Raised by", 1)[0]

    assert "storm-b/EL-0004" in table  # the notification that closed LL-A2
    assert "storm-b/EL-0005" in table
    for line in table.splitlines():
        if "LL-A" in line:
            assert "storm-" in line.split("[")[-1], f"unqualified citation in: {line}"


@pytest.mark.parametrize("mode", ["phantom", "foreign", "unsourced"])
def test_a_bad_draft_fails_the_run(store, tmp_path, mode):
    """The point of the whole build: a report that cannot be defended does not pass."""
    result = _run("storm-a", store, tmp_path, backend=MockSuperDocs(misbehave=mode))
    assert not result.ok
    assert result.trace.flagged


def test_an_invented_citation_is_named_in_the_report(store, tmp_path):
    result = _run("storm-a", store, tmp_path, backend=MockSuperDocs(misbehave="phantom"))
    assert result.trace.phantoms
    assert "EL-9999" in result.trace.phantoms[0].offending


def test_rejecting_a_change_leaves_the_placeholder_and_keeps_the_reason(store, tmp_path):
    """Rejection has to work, not just approval."""
    backend = MockSuperDocs()
    reject = lambda change: (False, "not supported by the records")  # noqa: E731
    result = _run("storm-a", store, tmp_path, backend=backend, approver=reject)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    assert "Placeholder for observed statements" in markdown
    assert backend.rejections
    assert backend.rejections[0] == "not supported by the records"


def test_rejecting_one_change_does_not_discard_the_others(store, tmp_path):
    """Item-by-item decisions, as the brief requires."""
    seen: list[str] = []

    def gate(change):
        seen.append(change.change_id)
        return (len(seen) != 1), "first one rejected"

    backend = MockSuperDocs()
    result = _run("storm-a", store, tmp_path, backend=backend, approver=gate)
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    assert len(seen) > 3
    assert len(backend.rejections) == 1
    assert "Placeholder" in markdown  # the rejected one stayed
    assert "EL-" in markdown  # the approved ones landed


def test_storm_b_opens_storm_as_lessons_because_it_read_them(store, tmp_path):
    """The carry-forward, seen from the finished document rather than the store."""
    _run("storm-a", store, tmp_path)
    result = _run("storm-b", store, tmp_path)

    assert result.carry == {
        "inherited": 3,
        "inherited_open": 2,
        "inherited_closed": 1,
        "raised_here": 1,
    }
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    assert "Carried forward from previous events" in markdown
    assert "LL-A2" in markdown and "Closed in storm-b" in markdown
    assert "LL-A1" in markdown and "Open" in markdown


def test_storm_a_alone_inherits_nothing(store, tmp_path):
    result = _run("storm-a", store, tmp_path)
    assert result.carry["inherited"] == 0
    markdown = result.exports["markdown"].read_text(encoding="utf-8")
    assert "Carried forward from previous events" not in markdown


def test_running_the_pair_twice_gives_the_same_register(store, tmp_path):
    _run("storm-a", store, tmp_path)
    _run("storm-b", store, tmp_path)
    first = store.read_text(encoding="utf-8")

    _run("storm-a", store, tmp_path)
    second_result = _run("storm-b", store, tmp_path)
    assert store.read_text(encoding="utf-8") == first
    assert second_result.carry["inherited"] == 3


def test_small_sample_mode_caps_billable_turns(store, tmp_path):
    result = _run("storm-a", store, tmp_path, sections_limit=2)
    assert result.edits == 2


def test_a_source_document_cannot_give_the_system_orders(store, tmp_path, monkeypatch):
    """A log note containing something instruction-shaped is evidence to report, never
    a command. The guard rides in every instruction the pipeline sends."""
    from afteraction import sections as S

    backend = MockSuperDocs()
    _run("storm-a", store, tmp_path, backend=backend)
    assert backend.instructions
    for instruction in backend.instructions:
        if "OBSERVED" in instruction or "Items raised by" in instruction:
            assert S.GUARD in instruction


def test_undrafted_sections_are_named_not_scored_as_failures(store, tmp_path):
    """A --limit run leaves later sections holding their placeholders. Scoring those as
    unsourced claims reported a false FAIL on an otherwise clean live run."""
    result = _run("storm-a", store, tmp_path, sections_limit=2)
    assert result.edits == 2
    assert result.skipped  # named explicitly
    assert result.ok  # what was drafted is fully traced
    assert not any("Placeholder" in r.sentence for r in result.trace.results)


def test_a_full_run_skips_nothing(store, tmp_path):
    result = _run("storm-a", store, tmp_path)
    assert result.skipped == []
