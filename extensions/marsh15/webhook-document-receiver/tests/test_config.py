import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "superdocs_api_key": SecretStr("test"),
        "webhook_secret": SecretStr("s" * 32),
        "github_webhook_secret": SecretStr("g" * 32),
        "management_token": SecretStr("m" * 32),
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def test_superdocs_url_requires_tls_off_loopback() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        _settings(superdocs_base_url="http://api.superdocs.app")


def test_loopback_superdocs_url_may_use_http() -> None:
    settings = _settings(superdocs_base_url="http://127.0.0.1:9000")
    assert settings.superdocs_base_url == "http://127.0.0.1:9000"


def test_worker_lease_must_cover_external_sequence() -> None:
    with pytest.raises(ValidationError, match="three SuperDocs request timeouts"):
        _settings(superdocs_timeout_seconds=30, worker_lease_seconds=60)
