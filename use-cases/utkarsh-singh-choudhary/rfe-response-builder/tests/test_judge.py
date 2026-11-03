"""Tests for rfe_response_builder/judge.py."""
import requests_mock

from rfe_response_builder.judge import QualityVerdict, grade_draft
from rfe_response_builder.superdocs_client import SuperDocsClient


def _client():
    return SuperDocsClient(api_key="sk_test_fake_key_not_real", retry_backoff_s=0)


def test_grade_draft_returns_strong_when_model_says_addresses_concern():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": '{"addresses_concern": true, "reasoning": "Directly cites the missing evidence."}',
                  "document_changes": {}},
        )
        result = grade_draft(client, "grading-session-1", "officer concern text", "draft text")
    assert result.verdict == QualityVerdict.STRONG
    assert result.reasoning == "Directly cites the missing evidence."


def test_grade_draft_returns_weak_when_model_says_does_not_address_concern():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": '{"addresses_concern": false, "reasoning": "Restates the petition instead."}',
                  "document_changes": {}},
        )
        result = grade_draft(client, "grading-session-1", "officer concern text", "draft text")
    assert result.verdict == QualityVerdict.WEAK
    assert result.reasoning == "Restates the petition instead."


def test_grade_draft_tolerates_markdown_fenced_json():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": '```json\n{"addresses_concern": true, "reasoning": "Good."}\n```',
                  "document_changes": {}},
        )
        result = grade_draft(client, "grading-session-1", "concern", "draft")
    assert result.verdict == QualityVerdict.STRONG


def test_grade_draft_returns_unknown_on_unparseable_response():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": "I cannot help with that request.", "document_changes": {}},
        )
        result = grade_draft(client, "grading-session-1", "concern", "draft")
    assert result.verdict == QualityVerdict.UNKNOWN


def test_grade_draft_returns_unknown_on_malformed_json():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": '{"addresses_concern": "yes probably"}', "document_changes": {}},
        )
        result = grade_draft(client, "grading-session-1", "concern", "draft")
    assert result.verdict == QualityVerdict.UNKNOWN


def test_grade_draft_returns_unknown_when_key_missing():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": '{"reasoning": "no verdict key here"}', "document_changes": {}},
        )
        result = grade_draft(client, "grading-session-1", "concern", "draft")
    assert result.verdict == QualityVerdict.UNKNOWN


def test_grade_draft_returns_unknown_instead_of_raising_when_grading_call_fails():
    client = _client()
    with requests_mock.Mocker() as m:
        m.post("https://api.superdocs.app/v1/chat", status_code=500, json={"detail": "down"})
        result = grade_draft(client, "grading-session-1", "concern", "draft")
    assert result.verdict == QualityVerdict.UNKNOWN
    assert "grading call failed" in result.reasoning


def test_grade_draft_uses_a_separate_session_from_drafting():
    """Grading must never happen on the drafting session -- it would
    pollute the document-editing conversation with grading chatter."""
    client = _client()
    with requests_mock.Mocker() as m:
        m.post(
            "https://api.superdocs.app/v1/chat",
            json={"response": '{"addresses_concern": true, "reasoning": "ok"}', "document_changes": {}},
        )
        grade_draft(client, "grading-only-session", "concern", "draft")
        sent_body = m.last_request.json()
    assert sent_body["session_id"] == "grading-only-session"
