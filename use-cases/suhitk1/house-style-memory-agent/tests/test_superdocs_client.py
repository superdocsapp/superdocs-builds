"""SuperDocs client tests. No key, no network.

Two kinds of test live here:

1. Behaviour tests against the fake.
2. **Contract tests against real captured responses** in
   tests/fixtures/real_responses/. These are the ones that would have caught
   the original client being written to the brief instead of to the API: a
   fake can agree with a wrong assumption, a captured response cannot.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superdocs.client import (ApprovalError, OperationLedger, PendingChange,
                              ProposedChangeParseError, SuperDocsClient,
                              SuperDocsError, parse_proposed_content)
from superdocs.fake import OXFORD_AFTER, OXFORD_BEFORE, FakeSuperDocs

REAL = Path(__file__).parent / "fixtures" / "real_responses"


def _client(**kw):
    fake = FakeSuperDocs(**kw)
    return SuperDocsClient(fake), fake


def _session(client):
    return client.init_session()


# --- the double parse, against a REAL captured payload --------------------

def test_real_mcp_payload_needs_exactly_one_more_parse():
    """Captured live: the MCP result's content[0].text is a JSON string.

    The JSON-RPC envelope was parse one; this is parse two; the result is an
    object and must not be parsed again.
    """
    captured = json.loads((REAL / "raw_mcp_chat_envelope.json").read_text())
    text_block = captured["mcp_result"]["content"][0]
    assert text_block["type"] == "text"
    assert isinstance(text_block["text"], str), "real payload is a string"

    parsed = parse_proposed_content(text_block["text"])
    assert isinstance(parsed, dict)
    assert "document_changes" in parsed
    assert isinstance(parsed["document_changes"], dict), \
        "after the second parse document_changes is already an object"
    # A third parse must not happen.
    assert parse_proposed_content(parsed["document_changes"]) is \
        parsed["document_changes"]


def test_real_pending_change_shape_round_trips():
    """pending_changes entries carry old_html/new_html, not a 'content' blob."""
    captured = json.loads((REAL / "chat_ask_every_time.json").read_text())
    pending = captured["document_changes"]["pending_changes"]
    assert pending, "captured response should contain a pending change"
    change = PendingChange.from_payload(pending[0])
    assert change.change_id
    assert change.old_html and change.new_html
    assert change.old_html != change.new_html


def test_real_response_uses_document_changes_not_proposed_changes():
    """Pins the shape the original client got wrong."""
    captured = json.loads((REAL / "chat_ask_every_time.json").read_text())
    assert "document_changes" in captured
    assert "proposed_changes" not in captured


def test_second_parse_is_the_last_one():
    payload = {"op": "replace", "text": "[1, 2]"}
    parsed = parse_proposed_content(json.dumps(payload))
    assert parsed["text"] == "[1, 2]" and isinstance(parsed["text"], str)


def test_non_json_string_is_an_error_not_a_silent_pass():
    with pytest.raises(ProposedChangeParseError, match="not JSON"):
        parse_proposed_content("this is just prose")


def test_client_parses_json_encoded_document_changes():
    client, _ = _client(encode_document_changes=True)
    session = _session(client)
    result = client.chat(session, "add the comma")
    assert result.updated_html, "second parse did not happen"
    assert isinstance(result.raw["document_changes"], str), "fake must encode"


def test_client_accepts_document_changes_already_an_object():
    client, _ = _client(encode_document_changes=False)
    result = client.chat(_session(client), "add the comma")
    assert result.updated_html


# --- session-shaped API ---------------------------------------------------

def test_init_session_requires_document_ids_even_when_empty():
    fake = FakeSuperDocs()
    assert "error" in fake.call("init_session", {})
    assert "session_id" in fake.call("init_session", {"document_ids": []})


def test_upload_uses_file_base64_and_a_session():
    client, fake = _client()
    session = _session(client)
    client.upload_document(session, "a.html", b"<h1>T</h1>")
    tool, params = fake.calls[-1]
    assert tool == "upload_document_base64"
    assert "file_base64" in params and "content_base64" not in params
    assert params["session_id"] == session


def test_export_returns_the_document_body():
    client, _ = _client()
    session = _session(client)
    client.upload_document(session, "a.html", b"<h1>T</h1><p>Body</p>")
    assert "Body" in client.export_document(session)


# --- approval flow --------------------------------------------------------

def test_approval_flow_applies_the_edit_end_to_end():
    client, fake = _client()
    session = _session(client)
    client.upload_document(session, "a.html",
                           f"<h1>D</h1><p>{OXFORD_BEFORE}</p>".encode())
    assert OXFORD_BEFORE in client.export_document(session)

    job_id = client.chat_async(session, "add the serial comma")
    job = client.wait_for_job(job_id, interval=0)
    assert job["status"] == "awaiting_approval"
    changes = client.pending_changes_of(job)
    assert len(changes) == 1

    assert client.approve_all_pending(session, job_id, changes) == 1
    assert OXFORD_AFTER in client.export_document(session)


def test_approving_without_a_change_id_is_refused_by_the_client():
    """Live, this call succeeds and applies nothing — the worst failure mode."""
    client, _ = _client()
    with pytest.raises(ApprovalError, match="requires a change_id"):
        client.approve_change("s", "j", "")


def test_a_job_only_approved_at_job_level_never_completes():
    """Pins the real behaviour the client guards against."""
    client, fake = _client()
    session = _session(client)
    job_id = client.chat_async(session, "add the comma")
    client.wait_for_job(job_id, interval=0)
    result = fake.call("approve_change", {"session_id": session,
                                          "job_id": job_id, "approved": True})
    assert result["batch_complete"] is False
    assert OXFORD_AFTER not in fake.sessions[session], "nothing was applied"


def test_in_progress_is_not_treated_as_terminal():
    """Treating in_progress as terminal made approval fail against a live job."""
    client, _ = _client(polls_before_terminal=3)
    session = _session(client)
    job_id = client.chat_async(session, "add the comma")
    assert client.wait_for_job(job_id, interval=0)["status"] == "awaiting_approval"


def test_wait_for_job_gives_up_loudly():
    client, _ = _client(polls_before_terminal=99)
    session = _session(client)
    job_id = client.chat_async(session, "add the comma")
    with pytest.raises(SuperDocsError, match="still"):
        client.wait_for_job(job_id, tries=3, interval=0)


# --- billing, measured ----------------------------------------------------

def test_only_an_applied_edit_is_billed():
    client, _ = _client()
    session = _session(client)
    client.chat(session, "add the comma")
    assert client.ledger.total_operations == 1


def test_a_chat_that_edits_nothing_is_free():
    client, _ = _client(edits_document=False)
    session = _session(client)
    result = client.chat(session, "just say hello")
    assert result.ops_charged == 0 and result.was_billable is False
    assert client.ledger.total_operations == 0
    assert client.ledger.unbilled_chats == 1


def test_non_chat_tools_are_free():
    client, _ = _client()
    session = _session(client)
    client.upload_document(session, "a.html", b"<p>x</p>")
    client.export_document(session)
    client.request_download_url(session)
    client.clear_cross_session_memory("k")
    assert client.ledger.total_operations == 0


def test_a_failed_call_is_not_billed():
    client, fake = _client()
    session = _session(client)
    fake.fail_next = "chat"
    with pytest.raises(SuperDocsError):
        client.chat(session, "edit")
    assert client.ledger.total_operations == 0
    assert client.ledger.errors == 1


def test_ledger_declares_its_cost_model_measured():
    assert OperationLedger().as_dict()["cost_model_measured_on"] == "2026-08-13"


# --- retries are free -----------------------------------------------------

def test_retries_cost_nothing_and_are_counted_as_such():
    """Design fact, not an implication: a failed or no-op chat is billed 0, so
    the retry policy never trades reliability against budget."""
    client, fake = _client(edits_document=False)
    session = _session(client)
    result = client.chat_with_retry(session, "edit", attempts=3, backoff=0)
    assert result.ops_charged == 0
    assert client.ledger.total_operations == 0
    assert client.ledger.free_retries == 2
    assert client.ledger.as_dict()["free_retries"] == 2


def test_retry_recovers_from_a_transient_failure_without_being_billed_twice():
    client, fake = _client()
    session = _session(client)
    fake.fail_next = "chat"
    result = client.chat_with_retry(session, "edit", attempts=3, backoff=0)
    assert result.was_billable is True
    assert client.ledger.total_operations == 1, "only the applied edit billed"
    assert client.ledger.errors == 1
    assert client.ledger.free_retries == 1


def test_a_non_retryable_error_is_not_retried():
    client, fake = _client()
    session = _session(client)
    fake.fail_next, fake.fail_retryable = "chat", False
    with pytest.raises(SuperDocsError):
        client.chat_with_retry(session, "edit", attempts=3, backoff=0)
    assert client.ledger.free_retries == 0


# --- memory primitives ----------------------------------------------------

def test_memory_key_is_the_per_customer_primitive_not_scope():
    """cross_session_scope is a list of SESSION ids restricting search; it is
    not customer isolation. Getting these two confused would have made the
    leakage test meaningless."""
    client, fake = _client()
    session = _session(client)
    client.chat(session, "note A", cross_session_memory=True,
                cross_session_memory_key="client_a")
    client.chat(session, "note B", cross_session_memory=True,
                cross_session_memory_key="client_b")
    assert set(fake.memories) == {"client_a", "client_b"}
    assert client.clear_cross_session_memory("client_a") == 1
    assert fake.memories["client_b"] == ["note B"]


def test_memory_defaults_to_off():
    client, fake = _client()
    client.chat(_session(client), "edit")
    _, params = fake.calls[-1]
    assert params["cross_session_memory"] is False
    assert params["cross_session_search"] is False
    assert "cross_session_memory_key" not in params


def test_scope_is_passed_through_when_given():
    client, fake = _client()
    session = _session(client)
    client.chat(session, "edit", cross_session_search=True,
                cross_session_scope=["session_one", "session_two"])
    _, params = fake.calls[-1]
    assert params["cross_session_scope"] == ["session_one", "session_two"]


def test_clear_rejects_a_malformed_response():
    class Weird:
        def call(self, tool, params):
            return {"removed": "two"}

    with pytest.raises(SuperDocsError, match="expected an int"):
        SuperDocsClient(Weird()).clear_cross_session_memory("k")
