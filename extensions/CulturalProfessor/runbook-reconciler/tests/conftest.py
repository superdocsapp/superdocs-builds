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
import threading
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


@pytest.fixture(autouse=True)
def no_leaked_threads(request: pytest.FixtureRequest) -> Iterator[None]:
    """A test that starts something must stop it, and this proves it per test.

    The suite runs an in-process HTTP stub, and the stub owns a server thread.
    Those threads are daemons, so they die with pytest and cannot pin a CPU
    after the run — but "cannot" should be a property somebody checks rather
    than a claim in a docstring, and the failure mode when it stops being true
    is a machine at 100% across every core with nothing obviously running.

    Only non-daemon threads are failed on. A daemon left behind is untidy; a
    non-daemon left behind will hold the interpreter open at exit, which is the
    one that turns into an incident. The test that leaked it is named, because
    finding that afterwards from a process list is miserable.
    """
    before = {t.ident for t in threading.enumerate()}
    yield
    leaked = [
        t for t in threading.enumerate() if t.ident not in before and t.is_alive() and not t.daemon
    ]
    if leaked:
        names = ", ".join(f"{t.name}" for t in leaked)
        pytest.fail(
            f"{request.node.name} leaked {len(leaked)} non-daemon thread(s): {names}. "
            f"Whatever started them has to stop them -- a thread that outlives the "
            f"test outlives the run."
        )


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def infra_dir() -> Path:
    return INFRA


@pytest.fixture(scope="session")
def runbooks_dir() -> Path:
    return RUNBOOKS
