"""End to end against the stand-in: the wiring, and the guarantees that ride on it.

The stand-in deliberately returns one row whose quote is nowhere in the thread. That row
is the point of most of these tests: a model will occasionally produce a confident,
well-formed, entirely invented commitment, and the only thing standing between that and
a letter somebody sends is the quote check.
"""

from __future__ import annotations

import email
import email.policy

from thread_to_letter import extract as extract_mod
from thread_to_letter import letter as letter_mod
from thread_to_letter.client import Client
from thread_to_letter.commitments import dangling_superseded
from thread_to_letter.draft import build_reply
from thread_to_letter.thread import Thread, load
from tests.conftest import ROOT


def test_extraction_verifies_every_quote(client: Client, thread: Thread) -> None:
    result = extract_mod.extract(client, thread, "s1")
    assert result.commitments, "the stand-in returns a table"
    invented = [c for c in result.commitments if not c.quote_found]
    assert len(invented) == 1
    assert invented[0].party == "Nobody"
    assert "do not appear in the thread" in invented[0].quote_note


def test_an_invented_commitment_never_reaches_the_letter(
    client: Client, thread: Thread
) -> None:
    """The whole safety property in one assertion."""
    result = extract_mod.extract(client, thread, "s2")
    assert all(c.quote_found for c in result.usable)
    assert "Nobody" not in {c.party for c in result.usable}


def test_only_firm_commitments_are_usable(client: Client, thread: Thread) -> None:
    result = extract_mod.extract(client, thread, "s3")
    statuses = {c.status for c in result.usable}
    assert statuses == {"firm"}
    # The hedge and the second-hand report were extracted, and kept, and refused.
    all_statuses = {c.status for c in result.commitments}
    assert {"hedged", "second-hand", "superseded"} <= all_statuses


def test_the_letter_states_the_confirmed_commitments_and_nothing_else(
    client: Client, thread: Thread
) -> None:
    result = extract_mod.extract(client, thread, "s4")
    confirmed = result.usable
    drafted = letter_mod.draft(client, thread, confirmed, "s4")

    for c in confirmed:
        assert c.obligation.split()[0].lower() in drafted.html.lower()
    assert "a commitment nobody made" not in drafted.html.lower()
    assert "should be able to" not in drafted.html.lower()


def test_a_thread_with_nothing_in_it_says_so(client: Client) -> None:
    """The honest empty answer. A letter recording nothing is more useful than an
    invented one, and it is the rarer output."""
    quiet = load(ROOT / "threads" / "scheduling-only.mbox")
    result = extract_mod.extract(client, quiet, "s5")
    assert result.found_nothing
    assert result.usable == []

    drafted = letter_mod.draft(client, quiet, [], "s5")
    assert drafted.states_nothing
    assert "no commitments" in drafted.html.lower()


def test_the_reply_draft_threads_and_carries_the_letter(
    client: Client, thread: Thread
) -> None:
    result = extract_mod.extract(client, thread, "s6")
    raw = build_reply(thread, result.usable, b"LETTER-BYTES", fmt="docx",
                      from_address="me@northwind.example")
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    assert msg["Subject"].startswith("Re: ")
    assert msg["In-Reply-To"] == thread.last_message_id, "otherwise it starts a new thread"
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_payload(decode=True) == b"LETTER-BYTES"

    body = msg.get_body(preferencelist=("plain",)).get_content()
    for c in result.usable:
        assert c.party in body
    assert "left out on purpose" in body


def test_the_run_is_two_billable_operations(client: Client, thread: Thread) -> None:
    """Everything else — parsing, checking, export, building the reply — is free."""
    extract_mod.extract(client, thread, "s7")
    letter_mod.draft(client, thread, [], "s7")
    client.export(session_id="s7", fmt="markdown")
    assert client.operations_spent == 2


def test_the_dangling_check_runs_on_real_extraction_output(
    client: Client, thread: Thread
) -> None:
    result = extract_mod.extract(client, thread, "s8")
    # The stand-in pairs its superseded row with a firm replacement, as a real
    # extraction should.
    assert dangling_superseded(result.commitments) == []
