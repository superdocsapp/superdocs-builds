import pytest

from src.esign_client import DocuSignMCPClient


def test_docusign_client_fails_clearly_without_credentials(monkeypatch):
    """Never silently proceeds without real credentials -- must raise, with a message that tells the
    person exactly what to do, rather than quietly returning a fake success."""
    monkeypatch.delenv("DOCUSIGN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("DOCUSIGN_ACCOUNT_ID", raising=False)

    with pytest.raises(ValueError) as exc_info:
        DocuSignMCPClient()

    assert "developer account" in str(exc_info.value).lower()


def test_docusign_client_uses_sandbox_url_by_default():
    client = DocuSignMCPClient(access_token="fake-token", account_id="fake-account")
    assert client.base_url == DocuSignMCPClient.SANDBOX_URL
    assert "mcp-d.docusign.com" in client.base_url


def test_docusign_client_can_target_production_explicitly():
    client = DocuSignMCPClient(access_token="fake-token", account_id="fake-account", use_sandbox=False)
    assert client.base_url == DocuSignMCPClient.PRODUCTION_URL
