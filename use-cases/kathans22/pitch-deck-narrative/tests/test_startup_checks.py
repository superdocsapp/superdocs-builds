"""Startup config checks print Cause + Fix."""

from __future__ import annotations

import os

import pytest

from generator.startup_checks import StartupConfigError, require_runtime_config


def test_placeholder_key_names_cause_and_fix(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SUPERDOCS_API_KEY", "your-key-here")
    with pytest.raises(StartupConfigError):
        require_runtime_config(require_api_key=True)
    err = capsys.readouterr().err
    assert "ERROR:" in err
    assert "Cause:" in err
    assert "Fix:" in err
    assert "your-key-here" in err or "placeholder" in err.lower()


def test_missing_key_names_cause_and_fix(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    with pytest.raises(StartupConfigError):
        require_runtime_config(require_api_key=True)
    err = capsys.readouterr().err
    assert "SUPERDOCS_API_KEY is not set" in err
    assert "Cause:" in err
    assert "Fix:" in err
    assert ".env.example" in err


def test_skip_api_key_still_requires_manifest(monkeypatch) -> None:
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    require_runtime_config(require_api_key=False)
