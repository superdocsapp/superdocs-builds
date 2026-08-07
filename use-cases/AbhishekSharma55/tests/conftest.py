"""Shared fixtures. Nothing here touches the network or needs a key."""

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def no_live_calls(monkeypatch):
    """Belt and braces: even if a test constructed a client by accident, there
    is no key in the environment for it to use, so it cannot spend money."""
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    monkeypatch.setenv("SUPERDOCS_RECORD", "0")


@pytest.fixture(scope="session")
def weeks():
    path = ROOT / "weekly-digest" / "data" / "weeks.json"
    if not path.exists():
        pytest.skip(f"{path} missing - run weekly-digest/data/build_corpus.py")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def repro_dir():
    return ROOT / "repro"
