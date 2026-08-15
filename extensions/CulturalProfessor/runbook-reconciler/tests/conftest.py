"""Fixtures shared by the suite.

The corpus is loaded once per session, not once per test. It is read-only —
every test that wants to mutate something copies it into `tmp_path` first — so
sharing it costs nothing and saves re-parsing a directory of YAML for each of
several dozen tests.

## The suite reads the corpus, whatever is in anyone's `.env`

`hermetic` is autouse and session-scoped, and it is the reason the suite is
worth trusting. `Config.load()` reads the real `.env`, so without it every test
that constructs a `Config` inherits whatever credentials the developer happens
to have — and the moment `page_source()` learned to prefer Confluence, `rr
check` under pytest started making live HTTP calls against a real site. A green
suite on this machine and a slow, network-dependent one on the next is not a
suite. `RR_SOURCE=corpus` pins it, and the one live test that genuinely wants a
site opts in through `RR_LIVE_CONFLUENCE_TESTS`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = PROJECT_ROOT / "fixtures"
INFRA = FIXTURES / "infra"
RUNBOOKS = FIXTURES / "runbooks"
EXPECTED = FIXTURES / "expected.yaml"


@pytest.fixture(scope="session", autouse=True)
def hermetic(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """No test reads Confluence, or the project's own register, by accident."""
    previous = {key: os.environ.get(key) for key in ("RR_SOURCE", "RR_REGISTER")}
    os.environ["RR_SOURCE"] = "corpus"
    # A test that forgets to point RR_REGISTER somewhere temporary would
    # otherwise write findings into the register.db this project ships its
    # measurement from. Under tmp rather than the project directory, so a run
    # that fails halfway leaves nothing behind to gitignore.
    os.environ["RR_REGISTER"] = str(tmp_path_factory.mktemp("register") / "register.db")
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def infra_dir() -> Path:
    return INFRA


@pytest.fixture(scope="session")
def runbooks_dir() -> Path:
    return RUNBOOKS
