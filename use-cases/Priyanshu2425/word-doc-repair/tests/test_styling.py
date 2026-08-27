"""The styling pass, which is the path this build actually promises.

The brief for this build says a strong result is a reviewer running a broken
DOCX through the tool and getting "a valid, styled file back with a clear
summary of what was recovered". So styling is not an extra beside the recovery;
it is the road the recovery takes, and the plain rebuild is what a person gets
when that road is closed.

Every test here runs without a network and without a key. A suite that needs a
live key to reach the success path only ever proves the failure path.
"""

from __future__ import annotations

import io
import json

import pytest
from starlette.testclient import TestClient

from tests import fixtures

from docrepair import docx, engine
from docrepair.docx import Block
from docrepair.superdocs_client import Styling
from docrepair.web import app


class FakeSuperDocs:
    """Stands in for the platform. Records what it was sent."""

    def __init__(self, outcome: Styling, expect=None):
        self.outcome = outcome
        self.sent: bytes | None = None
        self.stages: list[str] = []

    def style(self, sent: bytes, filename: str = "recovered.docx",
              on_progress=None) -> Styling:
        self.sent = sent
        if on_progress:
            for message in ("Sending the recovered document to SuperDocs…",
                            "Restoring heading styles, tables and spacing…"):
                on_progress("Styling", message)
                self.stages.append(message)
        return self.outcome


def _styled_from(sent: bytes) -> bytes:
    """A plausible styled return: same words, same pictures, different markup."""
    return sent


def _recovered():
    return engine.repair(fixtures.illustrated(), "site.docx")


# -- the flow ----------------------------------------------------------------

def test_the_styled_file_is_what_gets_handed_over():
    """`download` points at the styled file, not the plain rebuild — that is
    the whole difference between this being the product and being a button."""
    from docrepair.web import _style

    res = _recovered()
    fake = FakeSuperDocs(Styling(ok=True, output=_styled_from(res.output),
                                 note="SuperDocs returned a styled file.",
                                 ops_charged=1))

    out = _style(res, "/api/download/plain", lambda *a: None, client=fake)

    assert out["styled"] is True
    assert out["download"] != "/api/download/plain"
    assert out["plain_download"] == "/api/download/plain"


def test_the_plain_rebuild_stays_available_even_when_styling_worked():
    """Somebody who prefers the unstyled copy should not have to run it again."""
    from docrepair.web import _style

    res = _recovered()
    fake = FakeSuperDocs(Styling(ok=True, output=_styled_from(res.output)))

    out = _style(res, "/api/download/plain", lambda *a: None, client=fake)

    assert out["plain_download"] == "/api/download/plain"


def test_what_is_sent_to_superdocs_is_the_rebuilt_document_with_its_pictures():
    """Sent as a file, which is the documented contract — and the file is what
    carries the images, so they are not stripped on the way out."""
    from docrepair.web import _style

    res = _recovered()
    fake = FakeSuperDocs(Styling(ok=True, output=_styled_from(res.output)))

    _style(res, "/api/download/plain", lambda *a: None, client=fake)

    assert fixtures.media_names(fake.sent) == ["word/media/image1.png"]


def test_the_styling_steps_are_on_the_same_progress_stream():
    """One recovery to watch, not a recovery and then a decision nobody
    mentioned. The brief's first behaviour is steps you can watch."""
    from docrepair.web import _style

    seen: list[tuple[str, str]] = []
    res = _recovered()
    fake = FakeSuperDocs(Styling(ok=True, output=_styled_from(res.output)))

    _style(res, "/api/download/plain", lambda s, m: seen.append((s, m)), client=fake)

    assert any("SuperDocs" in message for _stage, message in seen)


# -- degradation -------------------------------------------------------------

@pytest.mark.parametrize("outcome,expect_rejected", [
    (Styling(ok=False, note="The styling pass did not work this time."), False),
    (Styling(ok=False, rejected_for_content=True,
             note="The styled version came back with the wording changed."), True),
])
def test_a_styling_failure_still_hands_over_the_recovered_document(
        outcome, expect_rejected):
    from docrepair.web import _style

    res = _recovered()
    fake = FakeSuperDocs(outcome)

    out = _style(res, "/api/download/plain", lambda *a: None, client=fake)

    assert out["styled"] is False
    assert out["plain_download"] == "/api/download/plain"
    assert out["styling_note"], "a degraded outcome with no reason is a bluff"
    assert out["styling_rejected"] is expect_rejected


def test_no_key_is_explained_rather_than_silently_skipped():
    from docrepair.superdocs_client import SuperDocsClient

    client = SuperDocsClient()
    client.api_key = None

    r = client.style(b"anything", "x.docx")

    assert r.ok is False
    assert "no SuperDocs key" in r.note
    assert r.stages == [], "nothing was sent, so nothing should be narrated"


def test_an_exhausted_allowance_spends_nothing(monkeypatch):
    """Refused before the first billable call, not discovered halfway."""
    from docrepair import superdocs_client as sc

    client = sc.SuperDocsClient(api_key="sk_test")
    monkeypatch.setattr(client, "allowance",
                        lambda: sc.Allowance(known=True, remaining=0))

    def explode(*a, **k):
        raise AssertionError("a billable call was made on an empty allowance")

    monkeypatch.setattr(client, "_upload_bytes", explode)
    monkeypatch.setattr(client, "_instruct", explode)

    r = client.style(b"doc", "x.docx")

    assert r.ok is False
    assert "used up" in r.note


def test_an_unreadable_allowance_is_not_treated_as_an_empty_one(monkeypatch):
    """`known=False` is "nobody read it", which is not "there is none left".
    Refusing on a number nobody read would be its own kind of bluff."""
    from docrepair import superdocs_client as sc

    client = sc.SuperDocsClient(api_key="sk_test")
    monkeypatch.setattr(client, "allowance", lambda: sc.Allowance(known=False))
    monkeypatch.setattr(client, "_upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(client, "_instruct", lambda *a, **k: None)
    monkeypatch.setattr(client, "_export", lambda *a, **k: b"")

    r = client.style(b"doc", "x.docx")

    assert "used up" not in r.note, "an unread balance was treated as empty"


# -- the guards --------------------------------------------------------------

def test_a_styled_file_that_lost_the_pictures_is_refused():
    """The styled file is the one offered as better, so it is the one that must
    not quietly be worse."""
    from docrepair.superdocs_client import _why_not_acceptable

    with_picture = _recovered().output
    without = docx.write_docx([Block("paragraph", "text only")])

    assert "fewer pictures" in _why_not_acceptable(with_picture, without)


def test_a_styled_file_with_invented_sentences_is_refused():
    """Observed live on 2026-08-20: a four-line report came back with invented
    paragraphs, a subtotal row, a disclaimer and a signature block."""
    from docrepair.superdocs_client import _why_not_acceptable

    sent = docx.write_docx([Block("paragraph", "one two three")])
    got = docx.write_docx([Block("paragraph", "one two three"),
                           Block("paragraph", "invented signature block")])

    assert "wording changed" in _why_not_acceptable(sent, got)


def test_a_faithful_restyle_is_accepted():
    """The guard has to be passable, or it is not a guard, it is a refusal."""
    from docrepair.superdocs_client import _why_not_acceptable

    sent = _recovered().output

    assert _why_not_acceptable(sent, sent) == ""
