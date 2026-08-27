"""Each run gets its own conversation.

A session id derived only from the thread meant every run of the same thread reused one
conversation, and turns accumulated. A live run with two dozen turns of history behind it
returned commitments about people who were not in the thread — the model answering from
the session rather than from the evidence.

Every one of those failed quote verification and nothing reached the letter. The safety
net held. These tests exist so it does not have to.
"""

from __future__ import annotations

from thread_to_letter.session import PREFIX, new_session
from thread_to_letter.thread import Thread


def test_two_runs_of_the_same_thread_get_different_sessions(thread: Thread) -> None:
    a = new_session(thread.normalised)
    b = new_session(thread.normalised)
    assert a != b, "reusing a session lets one run's history contaminate the next"


def test_the_thread_is_still_recognisable_in_the_name(thread: Thread) -> None:
    """So a session can be found in the web app when you go looking."""
    a, b = new_session(thread.normalised), new_session(thread.normalised)
    assert a.startswith(PREFIX) and b.startswith(PREFIX)
    # thread2letter-<12 hex of thread>-<nonce>
    assert a.split("-")[1] == b.split("-")[1]


def test_different_threads_are_distinguishable() -> None:
    assert new_session("one thread").split("-")[1] != new_session("another").split("-")[1]


def test_the_letter_gets_a_session_of_its_own_on_top(thread: Thread) -> None:
    """Two isolations, not one: fresh per run, and the drafting turn separate again so
    the thread in the extraction prompt cannot leak into the letter."""
    from thread_to_letter.letter import LETTER, MEMO

    base = new_session(thread.normalised)
    assert f"{base}-{LETTER}" != base
    assert f"{base}-{LETTER}" != f"{base}-{MEMO}"
