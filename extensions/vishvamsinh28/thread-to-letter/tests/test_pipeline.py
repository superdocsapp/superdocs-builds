"""End to end against the stand-in: the wiring, and the guarantees that ride on it.

The stand-in deliberately returns one row whose quote is nowhere in the thread. That row
is the point of most of these tests: a model will occasionally produce a confident,
well-formed, entirely invented commitment, and the only thing standing between that and
a letter somebody sends is the quote check.
"""

from __future__ import annotations

import email
import email.policy
import time

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


def test_the_letter_is_drafted_in_its_own_session(client: Client, thread: Thread) -> None:
    """The extraction session contains the entire thread. Drafting in it would let every
    hedge and retracted date the reviewer just excluded back into the letter."""
    extracted = extract_mod.extract(client, thread, "sess-x")
    drafted = letter_mod.draft(client, thread, extracted.usable, "sess-x")
    assert drafted.session_id != "sess-x"
    assert drafted.session_id.startswith("sess-x")

    memo = letter_mod.draft(client, thread, extracted.usable, "sess-x", shape="memo")
    assert memo.session_id != drafted.session_id, "a memo is not the same document as a letter"


def test_the_console_refuses_to_draft_a_decision_nobody_made(
    fake_server, tmp_path, monkeypatch
) -> None:
    """Candidates found and none ticked is not the same statement as "nothing was agreed",
    and only a person turns the first into the second. Spending an operation on the
    difference is exactly the surprise this build exists to avoid."""
    from fastapi.testclient import TestClient

    from thread_to_letter.web import create_app
    from tests.conftest import FAKE_KEY, ROOT

    monkeypatch.setenv("SUPERDOCS_API_KEY", FAKE_KEY)
    monkeypatch.setenv("SUPERDOCS_BASE_URL", fake_server.base_url)
    client = TestClient(create_app(str(ROOT / "threads")))

    client.post("/api/open", json={"name": "migration-project.mbox"})
    client.post("/api/extract")
    for _ in range(80):
        state = client.get("/api/state").json()
        if not state["busy"]:
            break
        time.sleep(0.2)
    assert state["commitments"], "the stand-in returns candidates"

    for c in state["commitments"]:
        client.post("/api/toggle", json={"quote": c["quote"], "on": False})

    refused = client.post("/api/letter", json={"shape": "letter"})
    assert refused.status_code == 400
    assert "Nothing is ticked" in refused.json()["detail"]
    assert not client.get("/api/state").json()["letter_html"]

    # Saying it explicitly is allowed, because now somebody has said it.
    allowed = client.post("/api/letter", json={"shape": "letter", "record_nothing": True})
    assert allowed.status_code == 200


def test_a_draft_can_be_discarded_and_the_demo_reset(
    fake_server, tmp_path, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    from thread_to_letter.web import create_app
    from tests.conftest import FAKE_KEY, ROOT

    monkeypatch.setenv("SUPERDOCS_API_KEY", FAKE_KEY)
    monkeypatch.setenv("SUPERDOCS_BASE_URL", fake_server.base_url)
    client = TestClient(create_app(str(ROOT / "threads")))

    client.post("/api/open", json={"name": "migration-project.mbox"})
    client.post("/api/extract")
    for _ in range(80):
        if not client.get("/api/state").json()["busy"]:
            break
        time.sleep(0.2)
    client.post("/api/letter", json={"shape": "letter"})
    for _ in range(80):
        if not client.get("/api/state").json()["busy"]:
            break
        time.sleep(0.2)
    assert client.get("/api/state").json()["draft"]

    # Discard keeps the review, so another letter can be written without paying again.
    client.post("/api/discard")
    after = client.get("/api/state").json()
    assert not after["draft"] and not after["letter_html"]
    assert after["commitments"], "the review survives a discarded draft"

    # Reset clears everything, including the record of what was called.
    client.post("/api/reset")
    blank = client.get("/api/state").json()
    assert blank["thread"] is None
    assert blank["commitments"] == []
    assert blank["call_seq"] == 0


def test_send_files_the_draft_in_sent(fake_server, monkeypatch) -> None:
    """Simulated, and labelled as such — but a Send button that does nothing is a dead
    button in the middle of the demo."""
    from fastapi.testclient import TestClient

    from thread_to_letter.web import create_app
    from tests.conftest import FAKE_KEY, ROOT

    monkeypatch.setenv("SUPERDOCS_API_KEY", FAKE_KEY)
    monkeypatch.setenv("SUPERDOCS_BASE_URL", fake_server.base_url)
    client = TestClient(create_app(str(ROOT / "threads")))

    assert client.get("/api/state").json()["sent"] == []
    assert client.post("/api/send").status_code == 400, "nothing to send yet"

    client.post("/api/open", json={"name": "migration-project.mbox"})
    client.post("/api/extract")
    for _ in range(80):
        if not client.get("/api/state").json()["busy"]:
            break
        time.sleep(0.2)
    client.post("/api/letter", json={"shape": "letter"})
    for _ in range(80):
        if not client.get("/api/state").json()["busy"]:
            break
        time.sleep(0.2)

    sent = client.post("/api/send")
    assert sent.status_code == 200
    state = client.get("/api/state").json()

    assert len(state["sent"]) == 1
    message = state["sent"][0]
    assert message["subject"].startswith("Re: ")
    assert "@" in message["to"]
    assert message["attachment"].endswith(".docx")
    assert message["commitments"], "it records what the letter actually stated"

    # Sending clears the draft — it is not in two places at once.
    assert state["draft"] is None

    # And it is still downloadable from Sent.
    download = client.get("/api/sent/0", params={"fmt": "markdown"})
    assert download.status_code == 200 and download.content

    # Reset clears the mailbox too.
    client.post("/api/reset")
    assert client.get("/api/state").json()["sent"] == []
