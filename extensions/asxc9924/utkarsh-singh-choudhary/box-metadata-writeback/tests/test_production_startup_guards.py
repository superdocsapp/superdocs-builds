"""The production startup guards in app/api/main.py (refuse to start
without WORKFLOW_API_KEYS, refuse to start without PERSISTENCE_DB_PATH,
both only when ENVIRONMENT=production) run at import time, which means
they can only be exercised once per process. These tests spawn a fresh
Python subprocess per case rather than importing the module in-process,
so each case gets a clean import.
"""
import os
import subprocess
import sys


def _run_import(env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app.api.main"],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_production_without_api_keys_refuses_to_start():
    result = _run_import(
        {
            "ENVIRONMENT": "production",
            "WORKFLOW_API_KEYS": "",
            "PERSISTENCE_DB_PATH": "/tmp/test_guard_dir",
        }
    )
    assert result.returncode != 0
    assert "WORKFLOW_API_KEYS" in result.stderr


def test_production_without_persistence_path_refuses_to_start():
    result = _run_import(
        {
            "ENVIRONMENT": "production",
            "WORKFLOW_API_KEYS": "some-real-key",
            "PERSISTENCE_DB_PATH": "",
        }
    )
    assert result.returncode != 0
    assert "PERSISTENCE_DB_PATH" in result.stderr


def test_production_with_both_configured_starts_cleanly():
    result = _run_import(
        {
            "ENVIRONMENT": "production",
            "WORKFLOW_API_KEYS": "some-real-key",
            "PERSISTENCE_DB_PATH": "/tmp/test_guard_ok_dir",
        }
    )
    assert result.returncode == 0, result.stderr


def test_development_mode_starts_without_either():
    result = _run_import(
        {
            "ENVIRONMENT": "development",
            "WORKFLOW_API_KEYS": "",
            "PERSISTENCE_DB_PATH": "",
        }
    )
    assert result.returncode == 0, result.stderr
