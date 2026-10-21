"""Config must fail fast on missing required settings, and load correctly when
they're present. See core/config.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_missing_required_config_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    # Also prevent a real .env file from satisfying the requirement in this test.
    monkeypatch.chdir("/tmp")

    from core.config import get_settings

    with pytest.raises(ValidationError):
        get_settings()


def test_valid_config_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/doctask_test"
    )

    from core.config import get_settings

    settings = get_settings()
    assert settings.environment == "development"
    assert str(settings.superdocs_base_url) == "https://api.superdocs.app/"
    # Secret must not leak into repr/str.
    assert "sk-ant-test" not in repr(settings.anthropic_api_key)
