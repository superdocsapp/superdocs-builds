import pytest

from connector.config import ConnectorConfig
from tests.conftest import FAKE_API_KEY, json_response


def test_config_rejects_empty_api_key():
    with pytest.raises(ValueError, match="non-empty api_key"):
        ConnectorConfig(api_key="")


def test_config_rejects_malformed_api_key_prefix():
    with pytest.raises(ValueError, match="does not look like a SuperDocs key"):
        ConnectorConfig(api_key="not-a-real-key-format")


def test_config_accepts_org_scoped_lce_key():
    config = ConnectorConfig(api_key="lce_abcdef1234567890")
    assert config.api_key.startswith("lce_")


def test_config_redacted_never_exposes_full_key():
    config = ConnectorConfig(api_key=FAKE_API_KEY)
    redacted = config.redacted()
    assert FAKE_API_KEY not in redacted
    assert repr(config) == redacted
    assert str(config) == redacted or "***" in str(config)


@pytest.mark.asyncio
async def test_authorization_header_is_sent_correctly(fake_server, client):
    seen_auth = {}

    def handler(request):
        seen_auth["value"] = request.headers.get("authorization")
        return json_response(200, {"ok": True})

    fake_server.on("GET", "/v1/sessions", handler)
    await client.get_json("/v1/sessions")

    assert seen_auth["value"] == f"Bearer {FAKE_API_KEY}"


@pytest.mark.asyncio
async def test_authorization_header_never_appears_in_debug_logs(fake_server, client, caplog):
    import logging
    caplog.set_level(logging.DEBUG, logger="superdocs_connector.http")

    fake_server.on("GET", "/v1/sessions", lambda r: json_response(200, {"ok": True}))
    await client.get_json("/v1/sessions")

    for record in caplog.records:
        assert FAKE_API_KEY not in record.getMessage()
        assert "***redacted***" in record.getMessage() or "authorization" not in record.getMessage().lower()
