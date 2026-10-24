import json

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.main import parse_payload


@pytest.fixture(autouse=True)
def configured_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SUPERDOCS_API_KEY", "test")
    monkeypatch.setenv("WEBHOOK_SECRET", "s" * 32)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "g" * 32)
    monkeypatch.setenv("MANAGEMENT_TOKEN", "m" * 32)
    monkeypatch.setenv("MAX_JSON_DEPTH", "5")
    monkeypatch.setenv("MAX_JSON_NODES", "100")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_rejects_json_nested_beyond_configured_depth() -> None:
    value: object = "leaf"
    for _ in range(6):
        value = {"nested": value}

    with pytest.raises(HTTPException, match="nested too deeply") as caught:
        parse_payload(json.dumps(value).encode())

    assert caught.value.status_code == 422


def test_rejects_excessive_json_node_count() -> None:
    with pytest.raises(HTTPException, match="too complex") as caught:
        parse_payload(json.dumps({"items": list(range(101))}).encode())

    assert caught.value.status_code == 422
