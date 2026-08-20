"""
These tests never hit the real network -- `requests_mock` intercepts every
call, so this file (and `make test-offline`) proves the integration logic
(payload shapes, response parsing, export flow, error handling) without
spending a SuperDocs operation or needing SUPERDOCS_API_KEY set.
"""
from pathlib import Path

import pytest
import requests_mock

from case_status_desk.generate import generate_letter, load_cases
from case_status_desk.superdocs_client import SuperDocsClient, SuperDocsError

DATA_FILE = Path(__file__).parent.parent / "data" / "sample_cases.json"


@pytest.fixture
def client():
    return SuperDocsClient(api_key="sk_test_fake_key_not_real")


def test_load_sample_cases_parses_all_three():
    cases = load_cases(DATA_FILE)
    assert len(cases) == 3
    assert {c.case_id for c in cases} == {"CASE-1001", "CASE-1002", "CASE-1003"}


def test_generate_letter_calls_chat_then_export(client, tmp_path):
    cases = load_cases(DATA_FILE)
    case = next(c for c in cases if c.case_id == "CASE-1001")

    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={
                "response": "Here's the letter.",
                "document_changes": {"updated_html": "<h1>Letter</h1>"},
                "usage": {"ops_charged": 1},
            },
        )
        m.post(
            "https://api.superdocs.app/v1/documents/export",
            content=b"FAKE_DOCX_BYTES",
        )

        out_path = generate_letter(client, case, tmp_path)

        assert out_path.exists()
        assert out_path.read_bytes() == b"FAKE_DOCX_BYTES"

        chat_req = m.request_history[0]
        assert chat_req.json()["session_id"] == "case-status-CASE-1001"
        assert "Degree Certificate" in chat_req.json()["message"]
        assert "Employment Verification Letter" not in chat_req.json()["message"].split("Outstanding documents:")[-1]

        export_req = m.request_history[1]
        assert export_req.json()["session_id"] == "case-status-CASE-1001"
        assert export_req.json()["format"] == "docx"


def test_client_raises_superdocs_error_on_4xx(client):
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            status_code=401,
            json={"detail": "Invalid API key"},
        )
        with pytest.raises(SuperDocsError, match="Invalid API key"):
            client.chat(session_id="s1", message="hello")


def test_client_export_propagates_bytes_unmodified(client):
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/documents/export", content=b"\x00binarydata")
        result = client.export(session_id="s1", fmt="pdf")
        assert result == b"\x00binarydata"


def test_wait_for_job_polls_until_terminal(client):
    with requests_mock.Mocker() as m:
        m.get(
            "https://api.superdocs.app/v1/jobs/job-1",
            [
                {"json": {"status": "processing"}},
                {"json": {"status": "processing"}},
                {"json": {"status": "completed", "document_changes": {"updated_html": "<p>done</p>"}}},
            ],
        )
        job = client.wait_for_job("job-1", poll_interval_s=0)
        assert job["status"] == "completed"


def test_approve_change_batch_payload(client):
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat/s1/approve", json={"status": "applied"})
        client.approve_change(
            session_id="s1",
            changes=[{"chunk_id": "c1", "approved": True}, {"chunk_id": "c2", "approved": False}],
        )
        sent = m.request_history[0].json()
        assert sent["changes"][1]["approved"] is False
