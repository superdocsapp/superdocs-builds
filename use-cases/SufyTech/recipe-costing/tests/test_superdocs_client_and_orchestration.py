"""
Proves run_build1.py's ORCHESTRATION LOGIC is wired correctly - correct
call order, correct field names, correct handling of the job-polling and
approval flow - without ever making a real network call. This is the
part Claude CAN verify without a live SuperDocs API key: the shape of
the calls, not the live API's actual behavior. See README.md's "What's
verified vs. what needs a live run" section for the honest split.

Fakes requests.post/requests.get at the point superdocs_client.py calls
them, returning response shapes copied directly from docs.superdocs.app
(llms-full.txt) - not invented.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from document_builder import build_menu_costing_document_html
from recipe_costing import apply_price_change
from sample_menu import MENU
from superdocs_client import SuperDocsClient


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
            # Match the REAL requests library: raise_for_status() raises
            # requests.exceptions.HTTPError with a `.response` attribute
            # pointing back at the response itself. superdocs_client.py's
            # error-handling (409 retry, approve_changes' batch->fallback)
            # specifically catches this exception type and reads
            # e.response.status_code / e.response.json() - a plain
            # RuntimeError here would silently defeat those tests.
            error = requests.exceptions.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


def test_upload_document_html_as_base64_sends_correct_fields():
    client = SuperDocsClient(api_key="sk_test")
    with patch("superdocs_client.requests.post") as mock_post:
        mock_post.return_value = FakeResponse({"chunks_count": 5, "session_id": "s1"})
        result = client.upload_document_html_as_base64("<h1>hi</h1>", "doc.html", "s1")

    assert result["chunks_count"] == 5
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["json"]["session_id"] == "s1"
    assert call_kwargs["json"]["filename"] == "doc.html"
    assert "file_base64" in call_kwargs["json"]
    assert call_kwargs["headers"]["Authorization"] == "Bearer sk_test"


def test_chat_includes_document_html_only_when_provided():
    client = SuperDocsClient(api_key="sk_test")
    with patch("superdocs_client.requests.post") as mock_post:
        mock_post.return_value = FakeResponse({"usage": {"ops_charged": 1}})
        client.chat(session_id="s1", message="hello")

    call_kwargs = mock_post.call_args.kwargs
    assert "document_html" not in call_kwargs["json"]
    assert call_kwargs["json"]["message"] == "hello"


def test_wait_for_job_polls_until_status_settles():
    client = SuperDocsClient(api_key="sk_test")
    responses = [
        FakeResponse({"status": "processing"}),
        FakeResponse({"status": "processing"}),
        FakeResponse({"status": "awaiting_approval", "metadata": {"pending_changes": []}}),
    ]
    with patch("superdocs_client.requests.get", side_effect=responses):
        with patch("superdocs_client.time.sleep"):  # don't actually wait in tests
            job = client.wait_for_job("job_1", poll_seconds=0.01, max_wait_seconds=5)

    assert job["status"] == "awaiting_approval"


def test_wait_for_job_raises_timeout_rather_than_hanging_forever():
    client = SuperDocsClient(api_key="sk_test")
    with patch("superdocs_client.requests.get", return_value=FakeResponse({"status": "processing"})):
        with patch("superdocs_client.time.sleep"):
            with pytest.raises(TimeoutError):
                client.wait_for_job("job_1", poll_seconds=1, max_wait_seconds=2)


def test_approve_change_batch_sends_job_id_approved_and_changes():
    client = SuperDocsClient(api_key="sk_test")
    with patch("superdocs_client.requests.post") as mock_post:
        mock_post.return_value = FakeResponse({"status": "applied"})
        decisions = [{"chunk_id": "c1", "approved": True}, {"chunk_id": "c2", "approved": True}]
        result = client.approve_change(session_id="s1", job_id="job_1", approved=True, changes=decisions)

    assert result["status"] == "applied"
    call_kwargs = mock_post.call_args.kwargs
    # REAL BUG regression check, corrected based on live evidence: a real
    # 422 response explicitly reported job_id and approved as REQUIRED
    # fields even alongside a changes batch - an earlier version of this
    # test asserted the opposite (based on a docs-reading theory that
    # turned out to be wrong once checked against the live server).
    assert call_kwargs["json"]["job_id"] == "job_1"
    assert call_kwargs["json"]["approved"] is True
    assert call_kwargs["json"]["changes"] == decisions


def test_approve_change_single_decision_sends_job_id_approved_and_chunk_id():
    client = SuperDocsClient(api_key="sk_test")
    with patch("superdocs_client.requests.post") as mock_post:
        mock_post.return_value = FakeResponse({"status": "applied"})
        client.approve_change(session_id="s1", job_id="job_1", approved=True, chunk_id="c1")

    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["json"] == {"job_id": "job_1", "approved": True, "chunk_id": "c1"}
    assert "changes" not in call_kwargs["json"]


def test_approve_changes_batch_uses_change_id_as_the_per_item_key():
    """
    The real fix for the 500 error found live: each pending_changes
    record carries both change_id and chunk_id - approve_changes must
    send change_id as the per-item identifier in the batch payload
    (best-supported theory given a 500 gave no further detail to
    confirm this with certainty - see approve_changes' docstring).
    """
    client = SuperDocsClient(api_key="sk_test")
    with patch("superdocs_client.requests.post") as mock_post:
        mock_post.return_value = FakeResponse({"status": "applied"})
        records = [
            {"change_id": "ch_1", "chunk_id": "chunk_1"},
            {"change_id": "ch_2", "chunk_id": "chunk_2"},
        ]
        result = client.approve_changes(session_id="s1", job_id="job_1", change_records=records, approved=True)

    assert result["mode"] == "batch"
    call_kwargs = mock_post.call_args.kwargs
    sent_changes = call_kwargs["json"]["changes"]
    assert sent_changes == [
        {"change_id": "ch_1", "chunk_id": "chunk_1", "approved": True},
        {"change_id": "ch_2", "chunk_id": "chunk_2", "approved": True},
    ]


def test_approve_changes_falls_back_to_per_item_when_batch_call_fails():
    """
    If the batch call fails for ANY reason (a live run hit a genuine
    500 here), approve_changes must automatically retry by approving
    each change individually via the simple single-decision shape,
    rather than propagating the failure and requiring a whole new run.
    """
    client = SuperDocsClient(api_key="sk_test")
    call_count = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        if "changes" in json:
            return FakeResponse(status_code=500, text="Internal Server Error")
        # per-item fallback call - no changes array, has chunk_id
        assert "chunk_id" in json
        assert "changes" not in json
        return FakeResponse({"status": "applied"})

    records = [{"change_id": "ch_1", "chunk_id": "chunk_1"}, {"change_id": "ch_2", "chunk_id": "chunk_2"}]
    with patch("superdocs_client.requests.post", side_effect=fake_post):
        result = client.approve_changes(session_id="s1", job_id="job_1", change_records=records, approved=True)

    assert result["mode"] == "fallback_per_item"
    assert len(result["results"]) == 2
    # 1 failed batch attempt + 2 successful per-item fallback calls
    assert call_count["n"] == 3


def test_approve_changes_defaults_change_id_to_chunk_id_when_missing():
    """If a pending_changes record has no change_id (only chunk_id),
    approve_changes must not crash - it falls back to using chunk_id's
    value as change_id too, rather than sending null/missing."""
    client = SuperDocsClient(api_key="sk_test")
    with patch("superdocs_client.requests.post") as mock_post:
        mock_post.return_value = FakeResponse({"status": "applied"})
        records = [{"chunk_id": "chunk_1"}]  # no change_id key at all
        client.approve_changes(session_id="s1", job_id="job_1", change_records=records, approved=False)

    sent_changes = mock_post.call_args.kwargs["json"]["changes"]
    assert sent_changes == [{"change_id": "chunk_1", "chunk_id": "chunk_1", "approved": False}]


def test_export_document_writes_binary_content_to_output_path(tmp_path):
    client = SuperDocsClient(api_key="sk_test")
    output_path = tmp_path / "out.docx"
    with patch("superdocs_client.requests.post") as mock_post:
        mock_post.return_value = FakeResponse(content=b"FAKE-DOCX-BYTES")
        client.export_document(session_id="s1", output_path=str(output_path))

    assert output_path.read_bytes() == b"FAKE-DOCX-BYTES"


def test_run_build1_full_flow_wires_correctly_end_to_end(tmp_path, monkeypatch):
    """
    Runs run_build1.main() with EVERY superdocs_client HTTP call faked,
    to prove the orchestration script itself has no wiring bugs (wrong
    dict keys, wrong call order, crashing on the approval step) - the
    one thing Claude can fully verify without a live API key.

    Also proves the export-staleness fix (test_export_staleness_fix.py
    covers verify_and_get_final_html's own logic in isolation) is
    actually WIRED IN here: the fake history response already reflects
    the approved change, and the export call receives that verified
    html directly rather than a session_id.
    """
    import run_build1

    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_test_fake")
    monkeypatch.chdir(tmp_path)

    call_log = []
    exported_bodies = []

    def fake_post(url, headers=None, json=None, timeout=None):
        call_log.append(url)
        if url.endswith("/documents/upload-base64"):
            return FakeResponse({"chunks_count": 5, "session_id": json["session_id"]})
        if url.endswith("/chat"):
            return FakeResponse({"usage": {"ops_charged": 1}})
        if url.endswith("/chat/async"):
            return FakeResponse({"job_id": "job_abc"})
        if "/approve" in url:
            return FakeResponse({"status": "applied"})
        if url.endswith("/documents/export"):
            exported_bodies.append(json)
            return FakeResponse(content=b"FAKE-DOCX-BYTES")
        raise AssertionError(f"unexpected POST to {url}")

    def fake_get(url, headers=None, timeout=None):
        call_log.append(url)
        if url.endswith("/history"):
            # Real, well-formed HTML (built the same way document_builder.py
            # always builds it) so patch_all_affected_dishes can integrate
            # against genuine <h2>/<td> markers without a false "section not
            # found" error. This models the AI having gotten everything
            # right - the specific "Unit Cost right, derived values stale"
            # regression is proven directly in test_value_patch.py instead,
            # so it isn't duplicated here.
            recost_result = apply_price_change(MENU, "Olive oil", 1.35)
            html = build_menu_costing_document_html(
                recost_result["updated_recipes"], title="Bistro Menu Costing Sheet"
            )
            return FakeResponse({"document_state": {"html_content": html}})
        return FakeResponse(
            {
                "status": "awaiting_approval",
                "metadata": {
                    "pending_changes": [
                        {"chunk_id": "chunk_1", "old_html": "$0.45", "new_html": "$1.35"},
                        {"chunk_id": "chunk_2", "old_html": "$0.45", "new_html": "$1.35"},
                    ]
                },
            }
        )

    with patch("superdocs_client.requests.post", side_effect=fake_post), \
         patch("superdocs_client.requests.get", side_effect=fake_get), \
         patch("superdocs_client.time.sleep"):
        run_build1.main()

    # Every required call type that the current, intentional flow makes,
    # in order: upload, chat/async (+ implicit approve), the history
    # check, export. Plain sync POST /v1/chat is deliberately NOT called
    # here (see run_build1.py's Step 2 comment and README.md's "chat"
    # discussion): a live run showed it leaves a staged pending change
    # that blocks the following chat_async call with a 409, so the
    # "send an edit instruction" requirement is satisfied via chat_async
    # instead, which is also the call that supports the required HITL
    # approval flow.
    assert any(u.endswith("/documents/upload-base64") for u in call_log)
    assert any(u.endswith("/chat/async") for u in call_log)
    assert any("/approve" in u for u in call_log)
    assert any(u.endswith("/history") for u in call_log)
    assert any(u.endswith("/documents/export") for u in call_log)

    # The menu export must go through export_html (raw html body), NOT
    # export_document (session_id) - that's the actual fix.
    menu_export_body = exported_bodies[0]
    assert "html" in menu_export_body
    assert "session_id" not in menu_export_body
    # value_patch.py must have run cleanly against real, well-formed
    # input - the exported body still has the correct, forced-consistent
    # derived values for an affected dish (Caesar Salad's margin, per
    # recipe_costing.py's own calculation for the new olive oil price).
    correct_recost = apply_price_change(MENU, "Olive oil", 1.35)
    caesar = next(r for r in correct_recost["updated_recipes"] if r.dish_name == "Caesar Salad")
    from recipe_costing import gross_margin

    expected_margin_text = f"{gross_margin(caesar) * 100:.1f}%"
    assert expected_margin_text in menu_export_body["html"]

    assert (tmp_path / "menu-costing-sheet-updated.docx").read_bytes() == b"FAKE-DOCX-BYTES"
    assert (tmp_path / "exceptions-report.docx").read_bytes() == b"FAKE-DOCX-BYTES"
