from pathlib import Path

import pytest

from config import (
    get_budget_floor,
    get_required_api_key,
    load_environment,
)


def test_load_environment_reads_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SUPERDOCS_API_KEY=test-key\n"
        "SUPERDOCS_BUDGET_FLOOR=15\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    monkeypatch.delenv("SUPERDOCS_BUDGET_FLOOR", raising=False)

    load_environment(tmp_path)

    assert get_required_api_key() == "test-key"
    assert get_budget_floor() == 15


def test_environment_variable_wins_over_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SUPERDOCS_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("SUPERDOCS_API_KEY", "environment-key")

    load_environment(tmp_path)

    assert get_required_api_key() == "environment-key"


def test_missing_api_key_fails_cleanly(monkeypatch):
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SUPERDOCS_API_KEY"):
        get_required_api_key()


def test_invalid_budget_floor_fails_cleanly(monkeypatch):
    monkeypatch.setenv("SUPERDOCS_BUDGET_FLOOR", "not-an-integer")

    with pytest.raises(RuntimeError, match="must be an integer"):
        get_budget_floor()