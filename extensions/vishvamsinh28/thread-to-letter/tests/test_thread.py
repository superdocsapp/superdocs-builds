"""Reading a thread. Offline, on real fixture files."""

from __future__ import annotations

from thread_to_letter.thread import Thread, load, parse_plain
from tests.conftest import ROOT


def test_an_mbox_becomes_ordered_messages(thread: Thread) -> None:
    assert len(thread.messages) == 8
    assert [m.index for m in thread.messages] == list(range(1, 9))
    assert thread.subject == "Data migration - kickoff and timings"
    assert len(thread.participants) == 3


def test_message_ids_survive_for_threading(thread: Thread) -> None:
    """Without these the reply starts a new conversation instead of joining this one."""
    assert thread.last_message_id == "<c8@northwind.example>"


def test_quoted_history_and_signatures_are_stripped() -> None:
    """Otherwise the same sentence appears in five messages and attribution is guesswork."""
    t = parse_plain(
        "From: A <a@x.example>\n"
        "Subject: Re: thing\n"
        "\n"
        "I will send the report on Friday.\n"
        "\n"
        "On Tue, B wrote:\n"
        "> we should probably do the thing\n"
        "> and another quoted line\n"
        "\n"
        "--\n"
        "A, Head of Everything\n"
    )
    body = t.messages[0].body
    assert "I will send the report on Friday." in body
    assert "quoted line" not in body
    assert "Head of Everything" not in body


def test_a_pasted_thread_is_accepted() -> None:
    """Somebody pasting out of Gmail should not have to reformat anything."""
    t = parse_plain(
        "From: Ann <ann@x.example>\nDate: Mon, 3 Mar 2026\nSubject: Hi\n\nFirst.\n\n"
        "From: Bob <bob@y.example>\nDate: Tue, 4 Mar 2026\nSubject: Re: Hi\n\nSecond.\n"
    )
    assert len(t.messages) == 2
    assert t.messages[0].sender == "Ann"
    assert t.messages[1].body.strip() == "Second."


def test_a_thread_with_no_commitments_still_parses() -> None:
    t = load(ROOT / "threads" / "scheduling-only.mbox")
    assert len(t.messages) == 3
    assert "quarterly" in t.subject.lower()


def test_the_rendered_thread_carries_stable_message_markers(thread: Thread) -> None:
    """An extracted commitment names the message it came from; that is only checkable
    if the model and the verifier agree on the numbering."""
    rendered = thread.render()
    for i in range(1, 9):
        assert f"--- message {i} ---" in rendered
