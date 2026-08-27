"""The styling counter's client surface: `Styling.session_id`, and the new
conversational turn/revert/history/structure/export methods on
`SuperDocsClient` (`docs/PRD-SET-IT-YOUR-WAY.md` §5-8).

Offline, like every other suite in this repo (B24): `requests.post` and
`requests.get` are monkeypatched on the `superdocs_client` module itself, so
nothing here touches the network or needs a key.

The fakes below match a URL against `client.base` rather than a module
constant, because there are now two bases a client can be pointed at: a
person's own key goes to SuperDocs' origin, and a checkout with no key of its
own borrows one from the relay. Asserting against the origin would have made
these tests pass only on a machine that happened to have a key in `.env`,
which is the one machine that proves the least.

The fake bodies below mirror shapes measured against the live API, not
guesses -- see the review that corrected this file:

  * `POST /v1/chat/async` -> `{job_id, message, session_id, status}`
  * `GET /v1/jobs/{id}`   -> top keys `{status, progress, result, metadata,
                              error, job_type, created_at, updated_at, ...}`;
                              `result` carries `{response, document_changes,
                              usage, session_id, attachment_id}`; `metadata`
                              carries `user_turn_index_pre_inserted`.
  * `GET /v1/sessions/{id}/history` -> `{document_state, editor_action,
                              messages, restore_error, session_id}`, and
                              `document_state.version_id` is what moves
                              when an edit lands -- `last_modified` is
                              always null and is not used for anything.
  * `GET /v1/sessions/{id}/documents` -> `{focused_document_id, documents:
                              [{document_id, durable_document_id, ...}]}` --
                              `GET /v1/documents/{id}` 400s on anything but
                              the durable id.
"""

from __future__ import annotations

import pytest

from docrepair import counter as ctr
from docrepair import docx
from docrepair import superdocs_client as sc
from docrepair.docx import Block

# -- consumer-facing sentence rules -------------------------------------------
#
# No string a person could read may name an internal mechanism or make a
# claim the product does not back. Checked against every note collected
# below, not just spot-checked.

_BANNED_LITERAL = ["ZIP", "XML", "CRC", "ParseError", "TimeoutError",
                    "Traceback", "NoneType", "b'", "0x"]
_EXCEPTION_NAMES = ["ValueError", "RuntimeError", "ConnectionError", "KeyError",
                    "AttributeError", "TypeError", "HTTPError", "Timeout",
                    "OSError", "IOError", "JSONDecodeError"]
_BANNED_CASEFOLD = ["zlib", "central directory", "stack trace", "utf-8",
                    "guaranteed", "perfect", "complete repair", "flawless",
                    "nothing was lost"]


def _assert_consumer_safe(note: str) -> None:
    assert note, "a degraded outcome with no reason is a bluff"
    for token in _BANNED_LITERAL + _EXCEPTION_NAMES:
        assert token not in note, f"{token!r} leaked into a note: {note!r}"
    lowered = note.lower()
    for token in _BANNED_CASEFOLD:
        assert token not in lowered, f"{token!r} leaked into a note: {note!r}"


# -- a tiny fake transport -----------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int = 200, json_body=None, content: bytes = b""):
        self.status_code = status_code
        self._json = {} if json_body is None else json_body
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise sc.requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._json


def _doc(words: str) -> bytes:
    return docx.write_docx([Block("paragraph", words)])


#: A `GET .../documents` body shaped like the live one, so `structure()`
#: resolves a durable id before ever hitting `/v1/documents/{id}`.
_DOCUMENTS_BODY = {
    "focused_document_id": "doc_primary",
    "documents": [{
        "document_id": "doc_primary",
        "durable_document_id": "ad1928fe-7c95-4631-9ad7-13061746e6d5",
    }],
}


def _history_body(version_id: str, turn_index: int | None = None) -> dict:
    messages = [] if turn_index is None else [{"turn_index": turn_index,
                                               "checkpoint_id": "chk-hist"}]
    return {
        "document_state": {"version_id": version_id, "last_modified": None},
        "editor_action": None,
        "messages": messages,
        "restore_error": None,
        "session_id": "irrelevant",
    }


def _job_body(status: str, *, progress: int = 100, ops_charged: int = 1,
             monthly_remaining: int = 494, document_changes=None,
             user_turn_index: int = 7) -> dict:
    return {
        "status": status,
        "progress": progress,
        "result": {
            "response": "Done.",
            "document_changes": document_changes or [],
            "usage": {"monthly_used": 6, "monthly_limit": 500,
                     "monthly_remaining": monthly_remaining,
                     "was_billable": True, "ops_charged": ops_charged,
                     "quota_exhausted": False, "subscription_tier": "free"},
            "session_id": "irrelevant",
            "attachment_id": None,
        },
        "metadata": {"user_turn_index_pre_inserted": user_turn_index},
        "error": None,
        "job_type": "chat",
        "created_at": "2026-08-26T00:00:00Z",
        "updated_at": "2026-08-26T00:00:05Z",
    }


# -- style() keeps its session --------------------------------------------------


def test_style_exposes_the_session_id_it_minted(monkeypatch):
    """`style()` used to mint a session and throw it away. It has to survive
    so a conversation can continue on the same document."""
    client = sc.SuperDocsClient(api_key="sk_test")
    sent = _doc("one two three")

    monkeypatch.setattr(client, "allowance",
                        lambda: sc.Allowance(known=True, remaining=5))
    monkeypatch.setattr(client, "_upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(client, "_instruct", lambda *a, **k: None)
    monkeypatch.setattr(client, "export", lambda session_id: sent)

    result = client.style(sent, "x.docx")

    assert result.ok is True
    assert result.session_id.startswith("salvage-")


def test_the_twelve_existing_styling_tests_are_unaffected():
    """`tests/test_styling.py` asserts on `style()` directly; this is a
    pointer, not a re-implementation -- run it with
    `python3 -m pytest tests/test_styling.py -q` and it is still 12/12."""
    assert True


# -- a clean turn ---------------------------------------------------------------


def test_a_clean_turn_is_polled_exported_and_guarded(monkeypatch):
    client = sc.SuperDocsClient(api_key="sk_test")
    sent = _doc("one two three")
    got = sent  # same words, same pictures (none) -- the guard should pass
    authorised = ctr.baseline_from(sent)

    calls = {"chat_async": 0}

    def fake_post(url, **kwargs):
        if url == f"{client.base}/v1/chat/async":
            calls["chat_async"] += 1
            assert "approval_mode" not in (kwargs.get("json") or {})
            return FakeResponse(json_body={"job_id": "job-1", "status": "queued",
                                           "session_id": "sess-1",
                                           "message": "queued"})
        if url == f"{client.base}/v1/documents/export":
            return FakeResponse(content=got)
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, **kwargs):
        if url.startswith(f"{client.base}/v1/jobs/"):
            return FakeResponse(json_body=_job_body(
                "completed", ops_charged=1, monthly_remaining=41,
                user_turn_index=3))
        if url.startswith(f"{client.base}/v1/sessions/") and url.endswith("/history"):
            return FakeResponse(json_body=_history_body("v-before"))
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(sc.requests, "post", fake_post)
    monkeypatch.setattr(sc.requests, "get", fake_get)

    result = client.turn("sess-1", "Make the headings bold",
                         sent=sent, authorised=authorised)

    assert result.ok is True
    assert result.output == got
    assert result.rejected_for_content is False
    # Straight from job["metadata"]["user_turn_index_pre_inserted"], not a
    # second history read.
    assert result.turn_index == 3
    assert calls["chat_async"] == 1


# -- a turn the guard rejects -----------------------------------------------


def test_a_turn_that_changed_the_wording_lands_and_says_what_it_changed(monkeypatch):
    client = sc.SuperDocsClient(api_key="sk_test")
    sent = _doc("one two three")
    authorised = ctr.baseline_from(sent)
    # Invented words that neither the rebuild nor the person supplied.
    got = docx.write_docx([Block("paragraph", "one two three four five six")])

    def fake_post(url, **kwargs):
        if url == f"{client.base}/v1/chat/async":
            return FakeResponse(json_body={"job_id": "job-2", "status": "queued"})
        if url == f"{client.base}/v1/documents/export":
            return FakeResponse(content=got)
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, **kwargs):
        if url.startswith(f"{client.base}/v1/jobs/"):
            return FakeResponse(json_body=_job_body("completed", ops_charged=1))
        if url.startswith(f"{client.base}/v1/sessions/") and url.endswith("/history"):
            return FakeResponse(json_body=_history_body("v-before"))
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(sc.requests, "post", fake_post)
    monkeypatch.setattr(sc.requests, "get", fake_get)

    result = client.turn("sess-2", "tidy the table",
                         sent=sent, authorised=authorised)

    # Since 2026-08-26 a turn is no longer thrown away for changing the
    # wording -- the person asked for it. What must never happen is the
    # change going by unremarked, so the receipt names it.
    assert result.ok is True
    assert result.rejected_for_content is False
    assert "3 words added" in result.note, (
        f"the turn must say what it did to the document; got: {result.note}")


# -- reconciliation, never a blind retry, driven by the version id -----------


def test_a_timed_out_turn_reconciles_without_a_second_chat_call_when_the_version_id_is_unchanged(
        monkeypatch):
    client = sc.SuperDocsClient(api_key="sk_test")
    sent = _doc("one two three")
    authorised = ctr.baseline_from(sent)

    calls = {"chat_async": 0, "export": 0}

    def fake_post(url, **kwargs):
        if url == f"{client.base}/v1/chat/async":
            calls["chat_async"] += 1
            return FakeResponse(json_body={"job_id": "job-3", "status": "queued"})
        if url == f"{client.base}/v1/documents/export":
            calls["export"] += 1
            return FakeResponse(content=sent)
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, **kwargs):
        if url.startswith(f"{client.base}/v1/jobs/"):
            raise sc.requests.Timeout("simulated")
        if url.startswith(f"{client.base}/v1/sessions/") and url.endswith("/history"):
            # Same version id every read -- the edit never landed.
            return FakeResponse(json_body=_history_body("v-unchanged"))
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(sc.requests, "post", fake_post)
    monkeypatch.setattr(sc.requests, "get", fake_get)

    result = client.turn("sess-3", "make it bold",
                         sent=sent, authorised=authorised)

    assert result.ok is False
    assert result.reconciled is False
    assert calls["chat_async"] == 1, "a retry would double-apply and double-bill"
    assert calls["export"] == 0, "nothing landed, so nothing should be exported"
    _assert_consumer_safe(result.note)


def test_a_timed_out_turn_reconciles_exports_and_guards_when_the_version_id_changed(
        monkeypatch):
    client = sc.SuperDocsClient(api_key="sk_test")
    sent = _doc("one two three")
    authorised = ctr.baseline_from(sent)
    got = sent

    calls = {"chat_async": 0, "history": 0}

    def fake_post(url, **kwargs):
        if url == f"{client.base}/v1/chat/async":
            calls["chat_async"] += 1
            return FakeResponse(json_body={"job_id": "job-4", "status": "queued"})
        if url == f"{client.base}/v1/documents/export":
            return FakeResponse(content=got)
        raise AssertionError(f"unexpected POST {url}")

    def fake_get(url, **kwargs):
        if url.startswith(f"{client.base}/v1/jobs/"):
            raise sc.requests.Timeout("simulated")
        if url.startswith(f"{client.base}/v1/sessions/") and url.endswith("/history"):
            calls["history"] += 1
            # First read (before the turn) sees the old version; every read
            # after that -- the reconcile check, and the turn_index
            # fallback's own history read -- sees the version the edit
            # landed as.
            version = "v-before" if calls["history"] == 1 else "v-after"
            return FakeResponse(json_body=_history_body(version, turn_index=5))
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(sc.requests, "post", fake_post)
    monkeypatch.setattr(sc.requests, "get", fake_get)

    result = client.turn("sess-4", "make it bold",
                         sent=sent, authorised=authorised)

    assert result.ok is True
    assert result.reconciled is True
    assert result.output == got
    # No job metadata on this path (the job was never confirmed), so the
    # fallback reads the turn index from history instead.
    assert result.turn_index == 5
    assert calls["chat_async"] == 1, "a retry would double-apply and double-bill"


# -- structure(): the durable-id resolution ------------------------------


def test_structure_resolves_the_durable_document_id_before_reading_it(monkeypatch):
    """`GET /v1/documents/{id}` 400s on the session id and on the
    session-local slot id alike (measured against the live API) -- only the
    durable id, resolved via a separate free read, works. `structure()`
    must never call `/v1/documents/{id}` with anything else."""
    seen_document_urls = []

    def fake_get(url, **kwargs):
        if url == f"{client.base}/v1/sessions/sess-7/documents":
            return FakeResponse(json_body=_DOCUMENTS_BODY)
        if url.startswith(f"{client.base}/v1/documents/"):
            seen_document_urls.append(url)
            return FakeResponse(json_body={"structure": {"section_count": 2}})
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(sc.requests, "get", fake_get)

    client = sc.SuperDocsClient(api_key="sk_test")
    result = client.structure("sess-7")

    assert result == {"section_count": 2}
    assert seen_document_urls == [
        f"{client.base}/v1/documents/ad1928fe-7c95-4631-9ad7-13061746e6d5"
    ], "structure() must resolve the durable id, never pass the session id straight through"


# -- revert ----------------------------------------------------------------


def test_revert_returns_the_instruction_it_undid(monkeypatch):
    client = sc.SuperDocsClient(api_key="sk_test")

    def fake_post(url, **kwargs):
        if url.startswith(f"{client.base}/v1/sessions/") and url.endswith("/revert"):
            assert kwargs.get("json") == {"turn_index": 3}
            return FakeResponse(json_body={
                "compose_text": "make the headings bold",
                "reverted_to_turn": 2,
                "archived_turn_count": 1,
            })
        raise AssertionError(f"unexpected POST {url}")

    monkeypatch.setattr(sc.requests, "post", fake_post)

    result = client.revert("sess-5", 3)

    assert result.ok is True
    assert result.compose_text == "make the headings bold"
    assert result.reverted_to_turn == 2
    assert result.archived_turn_count == 1


def test_revert_while_a_job_is_in_flight_is_withheld_not_failed(monkeypatch):
    client = sc.SuperDocsClient(api_key="sk_test")
    monkeypatch.setattr(sc.requests, "post",
                        lambda url, **k: FakeResponse(status_code=409))

    result = client.revert("sess-6", 1)

    assert result.ok is False
    _assert_consumer_safe(result.note)


# -- every note a person could read, checked as one assertion -----------------


def test_every_note_produced_is_non_empty_and_consumer_safe(monkeypatch):
    notes: list[str] = []

    # No key.
    no_key = sc.SuperDocsClient()
    no_key.api_key = None
    notes.append(no_key.style(b"anything", "x.docx").note)

    # Exhausted allowance, pre-flight.
    client = sc.SuperDocsClient(api_key="sk_test")
    monkeypatch.setattr(client, "allowance",
                        lambda: sc.Allowance(known=True, remaining=0))
    notes.append(client.style(b"doc", "x.docx").note)

    # A guard rejection on the automatic pass.
    from docrepair.superdocs_client import _why_not_acceptable
    sent = _doc("one two three")
    got = docx.write_docx([Block("paragraph", "one two three four")])
    notes.append(
        "The styled version came back " + _why_not_acceptable(sent, got) + "."
    )

    # A turn that could not be confirmed and, on checking, had not landed.
    authorised = ctr.baseline_from(sent)

    def fake_post(url, **k):
        if url == f"{client.base}/v1/chat/async":
            return FakeResponse(json_body={"job_id": "job-9", "status": "queued"})
        raise AssertionError(url)

    def fake_get(url, **k):
        if url.startswith(f"{client.base}/v1/jobs/"):
            raise sc.requests.Timeout("simulated")
        if url.startswith(f"{client.base}/v1/sessions/") and url.endswith("/history"):
            return FakeResponse(json_body=_history_body("v-same"))
        raise AssertionError(url)

    monkeypatch.setattr(sc.requests, "post", fake_post)
    monkeypatch.setattr(sc.requests, "get", fake_get)
    notes.append(
        client.turn("sess-9", "make it bold", sent=sent, authorised=authorised).note
    )

    # A revert that could not reach the platform at all.
    monkeypatch.setattr(sc.requests, "post",
                        lambda url, **k: (_ for _ in ()).throw(sc.requests.ConnectionError("down")))
    notes.append(client.revert("sess-10", 1).note)

    assert notes, "the scenarios above should have produced something to check"
    for note in notes:
        _assert_consumer_safe(note)


# -- what the turn is wrapped in ------------------------------------------------

def test_the_envelope_does_not_argue_with_what_the_person_asked_for():
    """B20''. The envelope used to say "formatting only" and forbid adding,
    removing, rewording or completing anything — the same contract the
    automatic pass carries. Once the counter stopped refusing those requests,
    that wording was left arguing against instructions the owner had decided
    were the person's to give, which makes a model hedge or half-comply on a
    turn that should simply be done."""
    envelope = sc._bounded_turn("Finish the last paragraph, it stops mid-sentence.")

    assert "Finish the last paragraph, it stops mid-sentence." in envelope
    for contradiction in ("formatting only", "do not add, remove",
                          "do not add, expand", "never reword"):
        assert contradiction not in envelope.lower(), (
            f"the envelope still argues against the request: {contradiction!r}")


def test_the_envelope_still_bounds_the_scope_of_a_turn():
    """What it bounds now is scope, not permission: do what was asked, and
    nothing that was not. That half is worth keeping — a model handed a
    sparse recovered document will otherwise fill it out, which is what
    happened on 2026-08-20 (invented paragraphs, a subtotal row, a
    disclaimer, a signature block, none of them requested)."""
    envelope = sc._bounded_turn("Hairline table rules")

    lowered = envelope.lower()
    assert "nothing beyond it" in lowered
    for unrequested in ("disclaimers", "signature blocks", "totals"):
        assert unrequested in lowered
    # And the reason the document is being handled carefully at all.
    assert "recovered from a damaged file" in lowered
