import base64
import json

import httpx
import pytest

from app.superdocs import SuperDocsClient, SuperDocsError, parse_pending_changes


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return SuperDocsClient("sk_test", http=http)


def test_requires_key():
    with pytest.raises(SuperDocsError):
        SuperDocsClient("")


def test_upload_encodes_base64():
    seen = {}

    def handler(req: httpx.Request):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"document_id": "d1"})

    c = _client(handler)
    c.upload_document("s1", "f.html", "<p>hi</p>")
    assert seen["body"]["session_id"] == "s1"
    assert base64.b64decode(seen["body"]["file_base64"]).decode() == "<p>hi</p>"


def test_chat_edit_sets_ask_every_time_and_returns_job():
    def handler(req: httpx.Request):
        body = json.loads(req.content)
        assert body["approval_mode"] == "ask_every_time"
        return httpx.Response(200, json={"job_id": "job42"})

    assert _client(handler).chat_edit("s1", "draft it", document_html="<p/>") == "job42"


def test_poll_returns_on_awaiting_approval():
    def handler(req):
        return httpx.Response(200, json={"status": "awaiting_approval", "metadata": {}})

    job = _client(handler).poll_job("job1", interval=0)
    assert job["status"] == "awaiting_approval"


def test_pending_changes_parses_metadata():
    job = {"metadata": {"pending_changes": [
        {"change_id": "c1", "operation": "edit", "ai_explanation": "why", "new_html": "<p/>"}]}}
    changes = _client(lambda r: httpx.Response(200)).pending_changes(job)
    assert changes[0].change_id == "c1"
    assert changes[0].summary == "why"


def test_approve_sends_decisions():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"applied": []})

    _client(handler).approve_changes("s1", "job1", [{"change_id": "c1", "approved": True}])
    assert seen["body"]["approved"] is True
    assert seen["body"]["changes"][0]["change_id"] == "c1"


def test_export_returns_bytes():
    c = _client(lambda r: httpx.Response(200, content=b"PK\x03\x04"))
    assert c.export_document("s1", "docx").startswith(b"PK")


def test_download_url_returns_signed_link():
    def handler(req):
        assert json.loads(req.content)["session_id"] == "s1"
        return httpx.Response(200, json={"download_url": "https://signed/x.docx",
                                         "filename": "x.docx", "expires_in_seconds": 900})

    dl = _client(handler).download_url("s1", "docx")
    assert dl["download_url"].startswith("https://") and dl["filename"] == "x.docx"


def test_focused_durable_id_reads_roster():
    def handler(req):
        return httpx.Response(200, json={"documents": [
            {"document_id": "d0", "durable_document_id": "dur-a", "focused": False},
            {"document_id": "d1", "durable_document_id": "dur-b", "focused": True}]})

    assert _client(handler).focused_durable_id("s1") == "dur-b"


def test_open_documents_posts_document_ids():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"opened": ["dur-b"], "documents": []})

    _client(handler).open_documents("s2", ["dur-b"])
    assert seen["body"]["document_ids"] == ["dur-b"]


def test_error_status_raises():
    c = _client(lambda r: httpx.Response(429, text="rate limited"))
    with pytest.raises(SuperDocsError):
        c.upload_document("s1", "f", "x")


def test_parse_pending_changes_handles_double_encoded_string():
    # The SSE proposed_change_batch.content trap: a JSON string within JSON.
    raw = json.dumps({"changes": [{"change_id": "c9"}]})
    assert parse_pending_changes(raw)[0]["change_id"] == "c9"


def test_parse_pending_changes_handles_list_and_none():
    assert parse_pending_changes([{"change_id": "c1"}])[0]["change_id"] == "c1"
    assert parse_pending_changes(None) == []
