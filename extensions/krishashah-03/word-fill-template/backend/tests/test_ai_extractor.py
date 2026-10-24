import json

import httpx
import pytest

from app.config import Settings
from app.services.ai_extractor import AIExtractionError, extract_fields_with_ai

FIELD_SCHEMA = {
    "employee.name": {"type": "string", "required": True},
    "employee.ctc": {"type": "number", "required": True},
}


def _settings(api_key: str) -> Settings:
    return Settings(
        openrouter_api_key=api_key,
        openrouter_base_url="https://example.invalid",
        openrouter_timeout_seconds=5,
    )


class _FakeResponse:
    def __init__(self, status_code, json_body=None, text_body=""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text_body

    def json(self):
        return self._json_body


async def test_extract_fields_missing_api_key_raises(monkeypatch):
    monkeypatch.setattr("app.services.ai_extractor.get_settings", lambda: _settings(""))

    with pytest.raises(AIExtractionError):
        await extract_fields_with_ai(FIELD_SCHEMA, "Some text")


async def test_extract_fields_malformed_json_response_raises(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(200, json_body={"choices": [{"message": {"content": "not valid json"}}]})

    monkeypatch.setattr("app.services.ai_extractor.get_settings", lambda: _settings("test-key"))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(AIExtractionError):
        await extract_fields_with_ai(FIELD_SCHEMA, "Some text")


async def test_extract_fields_unexpected_response_shape_raises(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(200, json_body={"unexpected": "shape"})

    monkeypatch.setattr("app.services.ai_extractor.get_settings", lambda: _settings("test-key"))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(AIExtractionError):
        await extract_fields_with_ai(FIELD_SCHEMA, "Some text")


async def test_extract_fields_http_error_status_raises(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(500, text_body="internal error")

    monkeypatch.setattr("app.services.ai_extractor.get_settings", lambda: _settings("test-key"))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(AIExtractionError):
        await extract_fields_with_ai(FIELD_SCHEMA, "Some text")


async def test_extract_fields_timeout_raises(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.services.ai_extractor.get_settings", lambda: _settings("test-key"))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(AIExtractionError):
        await extract_fields_with_ai(FIELD_SCHEMA, "Some text")


async def test_extract_fields_filters_keys_not_in_schema(monkeypatch):
    payload = {
        "employee.name": "Rahul Patel",
        "employee.ctc": "8 LPA",
        "employee.hallucinated_field": "should be dropped",
    }
    content_str = json.dumps(payload)

    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(200, json_body={"choices": [{"message": {"content": content_str}}]})

    monkeypatch.setattr("app.services.ai_extractor.get_settings", lambda: _settings("test-key"))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await extract_fields_with_ai(FIELD_SCHEMA, "Some text")
    assert result == {"employee.name": "Rahul Patel", "employee.ctc": "8 LPA"}


async def test_extract_fields_strips_markdown_code_fence(monkeypatch):
    payload = {"employee.name": "Rahul Patel", "employee.ctc": None}
    content_str = "```json\n" + json.dumps(payload) + "\n```"

    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(200, json_body={"choices": [{"message": {"content": content_str}}]})

    monkeypatch.setattr("app.services.ai_extractor.get_settings", lambda: _settings("test-key"))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await extract_fields_with_ai(FIELD_SCHEMA, "Some text")
    assert result == {"employee.name": "Rahul Patel", "employee.ctc": None}
