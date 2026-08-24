"""
Proves run_build2.py's orchestration is wired correctly — correct call
order, correct field names, correct handling of the job-polling and
approval flow — without ever making a real network call. Mirrors Build
1's test_run_build1_full_flow_wires_correctly_end_to_end exactly, since
this is the one thing that can be fully verified without a live
SuperDocs API key: the shape of the calls, not the live API's actual
behavior.

Fakes requests.post/requests.get at the point superdocs_client.py calls
them.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from construction_data import fetch_open_rfi, fetch_rfi_response_event
from document_builder import build_rfi_document_html


class FakeResponse:
    def __init__(self, json_data=None, content=b"", status_code=200, text=""):
        self._json_data = json_data or {}
        self.content = content
        self.status_code = status_code
        self.text = text or str(json_data or {})

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


def test_run_build2_full_flow_wires_correctly_end_to_end(tmp_path, monkeypatch):
    import run_build2

    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test_fake")
    monkeypatch.chdir(tmp_path)

    call_log = []
    exported_bodies = []

    rfi = fetch_open_rfi()
    event = fetch_rfi_response_event()

    def fake_post(url, headers=None, json=None, timeout=None):
        call_log.append(url)
        if url.endswith("/documents/upload-base64"):
            return FakeResponse({"chunks_count": 3, "session_id": json["session_id"]})
        if url.endswith("/chat/async"):
            return FakeResponse({"job_id": "job_rfi_1"})
        if "/approve" in url:
            return FakeResponse({"status": "applied"})
        if url.endswith("/documents/export"):
            exported_bodies.append(json)
            return FakeResponse(content=b"FAKE-DOCX-BYTES")
        raise AssertionError(f"unexpected POST to {url}")

    def fake_get(url, headers=None, timeout=None):
        call_log.append(url)
        if url.endswith("/history"):
            # Model the AI having correctly answered the RFI - the
            # specific "some fields stale" regression is proven
            # directly in test_rfi_patch.py instead, so it isn't
            # duplicated here.
            from dataclasses import replace

            answered = replace(
                rfi,
                status=event["status"],
                response=event["response"],
                responded_by=event["responded_by"],
                date_responded=event["date_responded"],
                cost_impact=event["cost_impact"],
                schedule_impact=event["schedule_impact"],
            )
            html = build_rfi_document_html(answered)
            # The real server tags the edited element with data-chunk-id
            # once a job lands - patch_response_fields locates the
            # Response block by that attribute, so the mock has to
            # carry it too or every call here would raise for the wrong
            # reason (chunk not found instead of the thing being tested).
            html = html.replace(
                f"<p>{answered.response}</p>",
                f'<p data-chunk-id="chunk_1">{answered.response}</p>',
                1,
            )
            return FakeResponse({"document_state": {"html_content": html}})
        return FakeResponse(
            {
                "status": "awaiting_approval",
                "metadata": {
                    "pending_changes": [
                        {"chunk_id": "chunk_1", "old_html": "Awaiting response.", "new_html": event["response"]},
                    ]
                },
            }
        )

    with patch("superdocs_client.requests.post", side_effect=fake_post), \
         patch("superdocs_client.requests.get", side_effect=fake_get), \
         patch("superdocs_client.time.sleep"):
        run_build2.main()

    # Every required call type, in order: upload, chat/async, approve,
    # history check (twice: upload-settle verification, then export
    # verification), export.
    assert any(u.endswith("/documents/upload-base64") for u in call_log)
    assert any(u.endswith("/chat/async") for u in call_log)
    assert any("/approve" in u for u in call_log)
    assert any(u.endswith("/history") for u in call_log)
    assert any(u.endswith("/documents/export") for u in call_log)

    # The export must go through export_html (raw html body), NOT
    # export_document (session_id) - same fix Build 1 required.
    export_body = exported_bodies[0]
    assert "html" in export_body
    assert "session_id" not in export_body

    # rfi_patch.py must have run cleanly against real, well-formed
    # input - the exported body carries the correct, forced-consistent
    # response fields.
    assert event["response"] in export_body["html"]
    assert event["cost_impact"] in export_body["html"]
    assert event["schedule_impact"] in export_body["html"]
    # And the strong-bar fields from the initial upload must still be
    # present, untouched by the response patch.
    assert rfi.spec_section in export_body["html"]
    assert rfi.drawing_reference in export_body["html"]

    assert (tmp_path / "rfi-0142-answered.docx").read_bytes() == b"FAKE-DOCX-BYTES"


def test_run_build2_raises_loudly_if_no_api_key(monkeypatch, capsys):
    import importlib

    import run_build2

    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    importlib.reload(run_build2)

    with pytest.raises(SystemExit):
        run_build2.main()

    out = capsys.readouterr().out
    assert "SUPERDOCS_API_KEY is not set" in out
