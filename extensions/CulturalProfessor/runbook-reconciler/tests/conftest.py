"""Fixtures shared by the suite.

The corpus is loaded once per session, not once per test. It is read-only —
every test that wants to mutate something copies it into `tmp_path` first — so
sharing it costs nothing and saves re-parsing a directory of YAML for each of
several dozen tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = PROJECT_ROOT / "fixtures"
INFRA = FIXTURES / "infra"
RUNBOOKS = FIXTURES / "runbooks"
EXPECTED = FIXTURES / "expected.yaml"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def infra_dir() -> Path:
    return INFRA


@pytest.fixture(scope="session")
def runbooks_dir() -> Path:
    return RUNBOOKS
