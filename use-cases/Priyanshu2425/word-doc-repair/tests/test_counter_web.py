"""The styling counter's session endpoints -- `docs/PRD-SET-IT-YOUR-WAY.md`.

Offline throughout: a fake stands in for `SuperDocsClient`, so nothing here
touches the network or needs a key (B24) -- important beyond principle, since
this checkout's own `.env` sets a real `SUPERDOCS_API_KEY`. The fake is
installed *before* the recovery itself, so the automatic styling pass inside
`/api/recover` never reaches for the real client either; it is injected by
patching `docrepair.superdocs_client.SuperDocsClient`, which is what every new
route in `web.py` constructs via a lazy, in-function import -- the same house
style `_style` already uses.
"""

from __future__ import annotations

import io
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests import fixtures

from docrepair import engine
from docrepair.web import app
import docrepair.web as web


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# -- the fake platform ---------------------------------------------------------

@dataclass
class FakeTurn:
    ok: bool = True
    output: bytes = b""
    note: str = "SuperDocs applied the change."
    rejected_for_content: bool = False
    turn_index: int = 1
    reconciled: bool = False
    stages: list = field(default_factory=list)


@dataclass
class FakeReverted:
    ok: bool = True
    note: str = "Put back."
    compose_text: str = ""
    reverted_to_turn: int = -1
    archived_turn_count: int = 1


class FakeClient:
    """Stands in for `SuperDocsClient` everywhere `web.py` constructs one --
    including the automatic pass inside `/api/recover`, so a recovery run
    under this fake never touches the network either. Records what it was
    sent, so a pre-flight refusal can be proven to have sent nothing."""

    def __init__(self, *, allowance_known=True, allowance_remaining=99,
                turn_result=None, revert_result=None, document_html=""):
        self.allowance_known = allowance_known
        self.allowance_remaining = allowance_remaining
        self._turn_result = turn_result
        self._revert_result = revert_result
        self._document_html = document_html
        self.allowance_calls = 0
        self.open_calls: list[tuple] = []
        self.turn_calls: list[str] = []
        self.revert_calls: list[int] = []

    # -- the automatic pass's interface (see superdocs_client.SuperDocsClient.style)
    def style(self, sent: bytes, filename: str = "recovered.docx", on_progress=None):
        from docrepair.superdocs_client import Styling
        return Styling(ok=False, note="Not exercised by the counter's own tests.")

    # -- the counter's interface --------------------------------------------
    def allowance(self):
        from docrepair.superdocs_client import Allowance
        self.allowance_calls += 1
        return Allowance(known=self.allowance_known, remaining=self.allowance_remaining)

    def open_session(self, rebuild: bytes, filename: str = "recovered.docx") -> str:
        self.open_calls.append((rebuild, filename))
        return "fake-session-1"

    def document_html(self, session_id: str) -> str:
        """SuperDocs' own rendering, which is what the page shows after a
        turn because it is the only one carrying formatting. Empty by
        default here so the tests that care about the fallback to a rebuilt
        preview still exercise it; set `document_html` to override."""
        return self._document_html

    def turn(self, session_id, message, *, sent, authorised, on_progress=None) -> FakeTurn:
        self.turn_calls.append(message)
        if on_progress:
            on_progress("Styling", "Sending your change to SuperDocs…")
            on_progress("Styling", "Applying it…")
        if callable(self._turn_result):
            return self._turn_result(message, sent, authorised)
        return self._turn_result or FakeTurn(output=sent + b"!" + message.encode())

    def revert(self, session_id, turn_index) -> FakeReverted:
        self.revert_calls.append(turn_index)
        return self._revert_result or FakeReverted()


def _recover(client: TestClient, monkeypatch, **fake_kwargs) -> tuple[dict, FakeClient]:
    """Install a fake client, then run a real recovery under it -- offline
    end to end, including the automatic styling pass this build never skips
    (B3). Returns the manifest and the fake, so a test can assert on both."""
    fake = FakeClient(**fake_kwargs)
    monkeypatch.setattr(
        "docrepair.superdocs_client.SuperDocsClient", lambda *a, **k: fake)

    res = client.post(
        "/api/recover", files={"file": ("site.docx", io.BytesIO(fixtures.illustrated()))})
    assert res.status_code == 200
    last = [line for line in res.text.splitlines() if line.startswith("data: ")][-1]
    return json.loads(last[len("data: "):]), fake


def _sse_events(res) -> list[dict]:
    assert res.status_code == 200
    return [json.loads(line[len("data: "):])
            for line in res.text.splitlines() if line.startswith("data: ")]


# -- open -> turn -> download ---------------------------------------------------

def test_open_then_turn_repoints_download_and_plain_download_stays_the_rebuild(
        client, monkeypatch):
    payload, fake = _recover(client, monkeypatch)
    token, plain = payload["token"], payload["plain_download"]

    opened = client.post(f"/api/style/{token}/open").json()
    assert opened["turns_left"] == web.TURNS_CAP
    assert opened["receipts"] == []

    events = _sse_events(client.post(f"/api/style/{token}/turn",
                                     json={"message": "Make the headings bigger"}))
    final = events[-1]

    assert final["applied"] is True
    assert final["download"] not in (None, plain)
    assert final["plain_download"] == plain           # B2
    assert final["turns_left"] == web.TURNS_CAP - 1
    assert fake.turn_calls == ["Make the headings bigger"]

    got = client.get(final["download"])
    assert got.status_code == 200


# -- the free "no" ---------------------------------------------------------------

def test_a_refusal_made_before_sending_sends_nothing(client, monkeypatch):
    # Driven by a limit rather than by what was asked for. Since 2026-08-26
    # the counter refuses nothing on content -- the person is driving, and
    # what they ask SuperDocs for is theirs to ask.
    payload, fake = _recover(client, monkeypatch,
                             allowance_known=True, allowance_remaining=0)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    events = _sse_events(client.post(
        f"/api/style/{token}/turn",
        json={"message": "Make the headings smaller"}))
    final = events[-1]

    assert final["applied"] is False
    assert final["turns_left"] == web.TURNS_CAP
    assert fake.turn_calls == [], "a pre-flight refusal must send nothing"


def test_the_turn_cap_refuses_the_eleventh_turn(client, monkeypatch):
    payload, fake = _recover(client, monkeypatch)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")
    web._SESSIONS[token].turns_used = web.TURNS_CAP   # ten already spent

    events = _sse_events(client.post(f"/api/style/{token}/turn",
                                     json={"message": "widen the margins"}))
    final = events[-1]

    assert final["applied"] is False
    assert "tenth change" in final["note"]
    assert fake.turn_calls == []


def test_a_zero_allowance_refuses_before_sending(client, monkeypatch):
    payload, fake = _recover(client, monkeypatch,
                             allowance_known=True, allowance_remaining=0)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    events = _sse_events(client.post(f"/api/style/{token}/turn",
                                     json={"message": "widen the margins"}))
    final = events[-1]

    assert final["applied"] is False
    assert fake.turn_calls == [], "nothing may be sent once the limit is reached"
    # The allowance still decides whether to send (B22). It is not what the
    # person is told about: they arrived with a broken file, not an account,
    # and a number describing our metering is not something they can act on.
    assert "allowance" not in final["note"].lower()
    assert "operation" not in final["note"].lower()
    assert final["note"], "a refusal with no reason is a bluff"


def test_an_unknown_allowance_does_not_refuse(client, monkeypatch):
    """`known=False` is "nobody read it", never treated as zero -- B22."""
    payload, fake = _recover(client, monkeypatch,
                             allowance_known=False, allowance_remaining=0)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    events = _sse_events(client.post(f"/api/style/{token}/turn",
                                     json={"message": "widen the margins"}))
    final = events[-1]

    assert final["applied"] is True
    assert fake.turn_calls == ["widen the margins"]


# -- progress, in order ----------------------------------------------------------

def test_stages_arrive_before_the_final_manifest_in_order(client, monkeypatch):
    payload, fake = _recover(client, monkeypatch)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    events = _sse_events(client.post(f"/api/style/{token}/turn",
                                     json={"message": "hairline table rules"}))

    assert len(events) >= 3
    for event in events[:-1]:
        assert "done" not in event
        assert "stage" in event and "message" in event
    assert events[-1]["done"] is True
    messages = [e["message"] for e in events[:-1]]
    assert messages == [
        "Sending your change to SuperDocs…",
        "Applying it…",
    ]


# -- revert -----------------------------------------------------------------------

def test_revert_restores_the_previous_version_and_returns_compose_text(client, monkeypatch):
    payload, fake = _recover(client, monkeypatch)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    first = _sse_events(client.post(f"/api/style/{token}/turn",
                                    json={"message": "hairline table rules"}))[-1]
    fake._revert_result = FakeReverted(compose_text="hairline table rules")
    second = _sse_events(client.post(f"/api/style/{token}/turn",
                                     json={"message": "bigger headings"}))[-1]
    assert first["download"] != second["download"]

    reverted = client.post(f"/api/style/{token}/revert").json()

    assert reverted["ok"] is True
    assert reverted["compose_text"] == "hairline table rules"
    # A fresh token, but the same bytes the first turn produced -- the
    # version stack popped back to it rather than merely renaming a file.
    assert client.get(reverted["download"]).content == client.get(first["download"]).content
    assert reverted["plain_download"] == payload["plain_download"]
    assert fake.revert_calls == [1]


# -- expiry and disposal -----------------------------------------------------------

def test_an_expired_session_answers_with_the_not_held_sentence(client, monkeypatch):
    payload, fake = _recover(client, monkeypatch)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")
    web._SESSIONS[token].last_used_at = time.time() - web.TTL_SECONDS - 1

    got = client.get(f"/api/style/{token}/session")

    assert got.status_code == 404
    assert "no longer being held" in got.json()["detail"]
    assert token not in web._SESSIONS


def test_delete_disposes_and_the_session_is_gone_afterwards(client, monkeypatch):
    payload, fake = _recover(client, monkeypatch)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")
    assert token in web._SESSIONS

    deleted = client.delete(f"/api/style/{token}/session")
    assert deleted.status_code == 200
    assert deleted.json()["disposed"] is True
    assert token not in web._SESSIONS

    got = client.get(f"/api/style/{token}/session")
    assert got.status_code == 404


# -- O3: engine.repair(out_dir=...) -------------------------------------------

def test_repair_out_dir_writes_into_that_directory():
    with tempfile.TemporaryDirectory() as d:
        res = engine.repair(fixtures.illustrated(), "site.docx", out_dir=d)

        assert res.ok is True
        assert res.output_path == str(Path(d) / "local_rebuild.docx")
        assert Path(res.output_path).read_bytes() == res.output


def test_repair_with_no_out_dir_behaves_exactly_as_before():
    res = engine.repair(fixtures.illustrated(), "site.docx")

    assert res.output_path == "local_rebuild.docx"


# -- what the ledger records, and what it says a thing cost ---------------------
#
# Three properties found missing during review, each the same shape: the page
# tells the person something about cost or history that is not what happened.
# The receipts are where V5 says which of the two kinds of no this was, so a
# refusal that leaves no trace is a change somebody asked for and can never
# afterwards see they asked for.

def test_a_refusal_made_before_sending_still_goes_in_the_ledger(client, monkeypatch):
    payload, fake = _recover(client, monkeypatch,
                             allowance_known=True, allowance_remaining=0)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    client.post(f"/api/style/{token}/turn",
                json={"message": "Make the headings smaller"})

    receipts = client.get(f"/api/style/{token}/session").json()["receipts"]
    assert len(receipts) == 1, "a refusal must leave a trace"
    assert receipts[0]["applied"] is False
    assert receipts[0]["turn_index"] is None      # never sent, nothing to revert
    assert fake.turn_calls == []


def test_a_turn_that_did_not_land_leaves_the_document_alone(client, monkeypatch):
    """Whatever went wrong, the previous version stands and the person is
    told in one sentence. What the attempt cost us is not on the page."""
    payload, fake = _recover(
        client, monkeypatch,
        turn_result=FakeTurn(ok=False,
                             note="SuperDocs could not apply that change, so "
                                  "your document is unchanged."))
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    final = _sse_events(client.post(f"/api/style/{token}/turn",
                                    json={"message": "Tighten the spacing"}))[-1]

    assert final["applied"] is False
    assert final["note"]
    assert "counted" not in final["note"].lower()


def test_a_refused_turn_does_not_leave_the_authorised_baseline_moved(
        client, monkeypatch):
    """B20'. The baseline moves only when the person's words actually landed.
    A turn that supplied text and was then refused must not go on authorising
    those words for every turn after it."""
    payload, fake = _recover(
        client, monkeypatch,
        turn_result=FakeTurn(ok=False, rejected_for_content=True,
                             note="That change did not land."))
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    client.post(f"/api/style/{token}/turn",
                json={"message": 'replace the last line with "and the crane is approved"'})

    state = client.get(f"/api/style/{token}/session").json()
    assert state["authored_words"] == 0, (
        "a refused turn must not leave its words authorised")


def test_an_applied_turn_does_move_the_baseline_and_counts_the_words(
        client, monkeypatch):
    """The other half of B27: words the person supplied and that did land are
    theirs, counted, and said out loud in the handover."""
    payload, fake = _recover(client, monkeypatch)
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    client.post(f"/api/style/{token}/turn",
                json={"message": 'replace the last line with "and the crane is approved"'})

    state = client.get(f"/api/style/{token}/session").json()
    assert state["authored_words"] == 5, "five words supplied, five counted as theirs"


# -- the sheet follows the file -------------------------------------------------
#
# V5's toggle asks "as it came back" against "with your changes". A toggle that
# cannot show the second half is decoration, and DESIGN.md is explicit that the
# verdict is a claim while the sheet is the thing itself.

def _a_changed_document() -> bytes:
    """A valid `.docx` that plainly differs from the recovery's own output, so
    a preview built from it cannot be mistaken for the one before it."""
    from docrepair import docx as _docx
    from docrepair.docx import Block

    return _docx.write_docx([
        Block("heading", "Site inspection", 2),
        Block("paragraph", "The east elevation, photographed on arrival:"),
        Block("paragraph", "No further defects were observed."),
    ])


def test_an_applied_turn_shows_the_changed_document_not_just_a_file(
        client, monkeypatch):
    changed = _a_changed_document()
    payload, fake = _recover(client, monkeypatch,
                             turn_result=FakeTurn(ok=True, output=changed))
    token = payload["token"]
    before = payload["preview_html"]
    client.post(f"/api/style/{token}/open")

    final = _sse_events(client.post(f"/api/style/{token}/turn",
                                    json={"message": "Plainer headings"}))[-1]

    assert final["applied"] is True
    assert final["preview_html"], "a turn that changed the document must show it"
    assert final["preview_html"] != before, (
        "the toggle needs two sides that actually differ")
    assert "Site inspection" in final["preview_html"]


def test_putting_a_change_back_puts_the_sheet_back_too(client, monkeypatch):
    changed = _a_changed_document()
    payload, fake = _recover(client, monkeypatch,
                             turn_result=FakeTurn(ok=True, output=changed))
    token = payload["token"]
    client.post(f"/api/style/{token}/open")
    client.post(f"/api/style/{token}/turn", json={"message": "Plainer headings"})
    assert client.get(f"/api/style/{token}/session").json()["preview_html"]

    client.post(f"/api/style/{token}/revert")

    state = client.get(f"/api/style/{token}/session").json()
    assert state["preview_html"] == "", (
        "a sheet still showing the change just put back is the page "
        "disagreeing with itself about what the document says")


def test_a_preview_that_cannot_be_read_costs_the_toggle_and_not_the_turn(
        client, monkeypatch):
    """An unreadable export must never fail a turn that otherwise landed."""
    payload, fake = _recover(client, monkeypatch,
                             turn_result=FakeTurn(ok=True, output=b"not a document"))
    token = payload["token"]
    client.post(f"/api/style/{token}/open")

    final = _sse_events(client.post(f"/api/style/{token}/turn",
                                    json={"message": "Tighter spacing"}))[-1]

    assert final["applied"] is True, "the turn still landed"
    assert final["preview_html"] == ""
    assert final["download"], "and the file is still there to download"
