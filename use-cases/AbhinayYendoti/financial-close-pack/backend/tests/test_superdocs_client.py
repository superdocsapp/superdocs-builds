import pytest

from backend.app.core.config import settings
from backend.app.integrations.superdocs.client import (
    MockSuperDocsClient,
    SuperDocsClient,
    SuperDocsResponseError,
    get_client,
    parse_proposed_changes,
)

VALID = {"section": "Revenue", "before_value": "5%", "after_value": "8%"}


def test_parses_superdocs_nested_json_string():
    payload = {"result": f'[{{"external_change_id":"c1","section":"Revenue","before_value":"5%","after_value":"8%"}}]'}

    changes = parse_proposed_changes(payload)

    assert changes[0]["external_change_id"] == "c1"


def test_rejects_malformed_nested_json_string():
    with pytest.raises(SuperDocsResponseError):
        parse_proposed_changes({"result": "{not-json"})


def test_rejects_a_non_list_payload():
    with pytest.raises(SuperDocsResponseError):
        parse_proposed_changes({"result": {"section": "Revenue"}})


def test_rejects_changes_missing_required_fields():
    """A change without before/after values would render an empty diff in the UI."""
    with pytest.raises(SuperDocsResponseError, match="before_value"):
        parse_proposed_changes({"result": [{"section": "Revenue", "after_value": "8%"}]})


def test_mock_mode_returns_reviewable_changes(monkeypatch):
    monkeypatch.setattr(settings, "superdocs_mode", "mock")
    assert isinstance(get_client(), MockSuperDocsClient)


def test_live_mode_requires_an_api_key(monkeypatch):
    """Previously a blank key produced silent 401s against the real API."""
    monkeypatch.setattr(settings, "superdocs_mode", "live")
    monkeypatch.setattr(settings, "superdocs_api_key", "")

    with pytest.raises(SuperDocsResponseError, match="SUPERDOCS_API_KEY"):
        get_client()


def test_live_mode_builds_a_client_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "superdocs_mode", "live")
    monkeypatch.setattr(settings, "superdocs_api_key", "sk-test")
    monkeypatch.setattr(settings, "superdocs_base_url", "https://example.test/")

    client = get_client()

    assert isinstance(client, SuperDocsClient)
    assert client.base_url == "https://example.test"


def test_unknown_mode_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "superdocs_mode", "sort-of-live")
    with pytest.raises(SuperDocsResponseError, match="Unknown SUPERDOCS_MODE"):
        get_client()


@pytest.mark.asyncio
async def test_mock_client_produces_complete_changes():
    changes = await MockSuperDocsClient().edit_document("doc-1", "instruction")

    assert len(changes) == 3
    for change in changes:
        assert change["section"] and change["before_value"] and change["after_value"]
