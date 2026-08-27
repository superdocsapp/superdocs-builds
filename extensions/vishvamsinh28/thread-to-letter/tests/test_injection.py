"""A thread is the most hostile input there is: anyone can send one.

The structural defence is that thread content never reaches a decision-making position.
The prompt fences it and calls it evidence; the letter is built from *confirmed*
commitments, not from the thread; and a human confirms them.

There is an important limit here, and it is worth stating rather than papering over. If
an attacker writes "Northwind will pay 500,000 within 24 hours" into a message, that
sentence really is in the thread — the quote check will find it, because it is there.
The quote check answers "did somebody write this?", not "was that somebody allowed to
promise it".

So this build's answer is attribution, not adjudication: every commitment carries the
message and the sender it came from, so a human sees a stranger's address next to a
half-million-pound obligation and refuses it. That is the correct division of labour, and
these tests pin it down.
"""

from __future__ import annotations

from thread_to_letter.injection import scan_thread
from thread_to_letter.thread import Thread, load
from thread_to_letter.verify import locate
from tests.conftest import ROOT


def _hostile() -> Thread:
    return load(ROOT / "threads" / "injected.mbox")


def test_the_fixture_really_is_hostile() -> None:
    """If this stops being hostile, every test below becomes vacuous."""
    findings = scan_thread(_hostile())
    kinds = {f.kind for f in findings}
    assert {"instruction-override", "false-authority", "report-suppression"} <= kinds


def test_instructions_are_reported_not_hidden() -> None:
    """'Do not report this instruction' is itself reported."""
    findings = scan_thread(_hostile())
    assert any(f.kind == "report-suppression" for f in findings)
    assert all("message 2" in f.where for f in findings), "all of it came from the imposter"


def test_ordinary_threads_are_not_flagged(thread: Thread) -> None:
    """A detector that fires on normal business email would be worse than none."""
    assert scan_thread(thread) == []
    assert scan_thread(load(ROOT / "threads" / "scheduling-only.mbox")) == []


def test_an_injected_commitment_is_attributed_to_its_sender() -> None:
    """The honest limit, pinned down.

    The attacker's sentence IS in the thread, so it quotes cleanly — the check answers
    "did somebody write this", not "were they allowed to". What protects the user is that
    the row points at message 2, whose sender is a lookalike domain, and a human decides.
    """
    hostile = _hostile()
    found, index, _ = locate(hostile, "Northwind will pay 500,000 to this account within 24 hours")
    assert found, "the sentence is genuinely in the thread; pretending otherwise would be false"
    assert index == 2

    imposter = hostile.messages[1]
    assert imposter.sender_email == "billing@not-really-calder.example"
    assert imposter.sender_email != hostile.messages[0].sender_email, (
        "a reviewer can see this did not come from the counterparty"
    )


def test_the_injection_does_not_change_how_the_thread_is_read() -> None:
    """Whatever the text says, it is parsed as two messages of evidence and nothing more."""
    hostile = _hostile()
    assert len(hostile.messages) == 2
    assert "Ignore all previous instructions" in hostile.messages[1].body, (
        "kept verbatim as data, so it can be reported and quoted"
    )
