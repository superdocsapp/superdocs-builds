"""The parts worth testing run without a key, a network, or an operation.

Everything here is the judgement the build makes *before* it spends anything:
what the invitation says, what belongs in this brief, and how calendar and mail
become something the platform will accept. Those are the decisions that make a
brief specific to one meeting, and they are all local and deterministic.

The API calls are not mocked. A test that proves a mock returns what the mock
was told to return proves nothing, and the task document says so explicitly.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brief import parse_invite, score_source, select_sources, Source
from render import prepare_for_upload, render_eml, render_ics

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "meeting-2026-08-20-trellis"
TODAY = date(2026, 8, 14)


@pytest.fixture
def meeting():
    return parse_invite(FIXTURES / "invite.ics")


def test_the_invitation_says_what_the_meeting_is(meeting):
    assert meeting.title == "Q3 Partnership Review — Trellis Diagnostics"
    assert meeting.when.date() == date(2026, 8, 20)
    assert meeting.organiser == "Amara Osei"
    assert len(meeting.attendees) == 4
    assert ("Priyanka Raman", "p.raman@trellisdx.example") in meeting.attendees
    assert meeting.agenda == [
        "Integration milestone status",
        "Pricing schedule for renewal",
        "Open actions from Q2 review",
        "AOB",
    ]


def test_agenda_keywords_exclude_words_common_to_every_meeting(meeting):
    """`meeting`, `review` and `agenda` describe every meeting ever held, so
    letting them count would make any document look relevant to any meeting."""
    assert "milestone" in meeting.keywords
    assert "renewal" in meeting.keywords
    for noise in ("meeting", "review", "agenda", "the", "for"):
        assert noise not in meeting.keywords


def test_the_irrelevant_email_is_left_out(meeting):
    """The planted test. A facilities notice about car park resurfacing shares a
    company domain and a recent date with everything else in the folder, and
    nothing else. It must not reach the model, let alone the executive."""
    sources = select_sources(
        [p for p in FIXTURES.iterdir() if p.name != "invite.ics"], meeting, today=TODAY
    )
    by_name = {s.name: s for s in sources}

    assert by_name["thread-unrelated.eml"].selected is False
    assert by_name["thread-pricing.eml"].selected is True
    assert by_name["thread-integration.eml"].selected is True
    assert by_name["past-q2-minutes.md"].selected is True


def test_every_decision_carries_its_reason(meeting):
    """A brief that cannot say why something is in it cannot be argued with,
    and an executive who cannot argue with it stops trusting it."""
    for source in select_sources(
        [p for p in FIXTURES.iterdir() if p.name != "invite.ics"], meeting, today=TODAY
    ):
        assert source.reasons, f"{source.name} was judged with no reason recorded"
        if not source.selected:
            # A dropped source may still have weak signals — sharing a domain,
            # being recent. What must always be present is the shortfall itself,
            # so the threshold is something a team can argue with and move.
            assert any("against the" in r and "needed" in r for r in source.reasons), (
                f"{source.name} was dropped without saying by how much"
            )


def test_sharing_a_domain_is_not_enough_to_be_relevant(meeting):
    """Otherwise every internal email qualifies for every internal meeting."""
    only_domain = Source(
        path=Path("all-staff.eml"),
        text="From: facilities@harrowgate.example\nThe lifts are being serviced.",
    )
    scored = score_source(only_domain, meeting, today=TODAY)
    assert scored.score < 6.0


def test_a_document_about_the_subject_survives_being_old(meeting):
    """Recency is a tie-break, not a qualification. A contract signed two years
    ago is the most relevant document in the room at a renewal review."""
    contract = Source(
        path=Path("contract.md"),
        text=(
            "Trellis Diagnostics agreement. Platform fee. Renewal. Milestone "
            "change control. Commencement 1 October 2024."
        ),
    )
    assert score_source(contract, meeting, today=TODAY).score >= 6.0


# --- calendar and mail have to become something the platform accepts --------


def test_an_invitation_renders_to_markdown_without_losing_the_people():
    rendered = render_ics(FIXTURES / "invite.ics")
    assert "Q3 Partnership Review" in rendered
    for who in ("Amara Osei", "Daniel Kerr", "Priyanka Raman", "Stefan Lindqvist"):
        assert who in rendered
    assert "2026-08-20 09:30" in rendered
    assert "chair" in rendered.lower()


def test_an_email_renders_with_its_quoted_history_marked():
    """The earlier turns of a thread are frequently where the commitment being
    reviewed was actually made, so they are kept — but marked, so a reply is
    never mistaken for the message it replies to."""
    rendered = render_eml(FIXTURES / "thread-integration.eml")
    assert "26 September" in rendered
    assert "**From:** Daniel Kerr" in rendered
    assert any(line.startswith("> ") for line in rendered.splitlines())


def test_a_rendered_file_names_the_original_it_came_from():
    """So a claim in the brief can be walked back to a real message on disk."""
    rendered = render_ics(FIXTURES / "invite.ics")
    assert "invite.ics" in rendered.splitlines()[0]


def test_only_formats_the_api_rejects_are_converted(tmp_path):
    """Converting a .docx to Markdown to satisfy a rule that does not apply
    would throw away the tables and styling the platform is good at keeping."""
    converted, was_converted = prepare_for_upload(FIXTURES / "invite.ics", tmp_path)
    assert was_converted and converted.suffix == ".md"

    untouched, was_converted = prepare_for_upload(FIXTURES / "past-q2-minutes.md", tmp_path)
    assert not was_converted and untouched == FIXTURES / "past-q2-minutes.md"


def test_a_folder_without_an_invitation_is_refused(tmp_path):
    """Without an invitation this is a pile of documents about a supplier, not
    a brief for one meeting — which is the whole distinction the card draws."""
    from brief import build

    (tmp_path / "note.md").write_text("something", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="no .ics invitation"):
        build(tmp_path, client=None, session_id="unused")
