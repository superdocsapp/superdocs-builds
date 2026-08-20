"""`builds/poa-generator/` is a codebase, not an installed package.

The directory name carries a hyphen on purpose - it is an application folder,
not an import path - so the importable package inside it is `poa` and this file
is what puts it on `sys.path` for the suite. Nothing here imports from
`system/`, and `tests/test_isolation.py` fails the build if it ever does.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent.parent

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
# tests/ carries helpers (`recorded.py`, `simulator.py`). They are not a
# package, so their directory goes on the path too.
if str(APP_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(APP_ROOT / "tests"))


@pytest.fixture(scope="session")
def config() -> Path:
    return APP_ROOT / "config"


@pytest.fixture(scope="session")
def intakes() -> Path:
    return APP_ROOT / "intakes"


@pytest.fixture(scope="session")
def evidence() -> Path:
    return REPO_ROOT / "docs" / "evidence"


@pytest.fixture(scope="session")
def library(config: Path):
    from poa.library import Library

    return Library(config)


# Assembled once, handed out as a copy. A `Draft` is mutable, several tests
# doctor one on purpose, and a session-scoped fixture handed out by reference
# means a test that forgets to restore it breaks a different test in a different
# file - which is exactly what happened while these were being written, and it
# took a full-suite run to see because each file passed on its own.
@pytest.fixture(scope="session")
def _assembled(library, intakes: Path) -> dict:
    from poa.assemble import assemble
    from poa.intake import load_intake

    return {
        name: assemble(load_intake(intakes / f"{name}.json", library), library)
        for name in ("durable-financial", "healthcare", "limited-real-property")
    }


@pytest.fixture
def financial(_assembled):
    return deepcopy(_assembled["durable-financial"])


@pytest.fixture
def healthcare(_assembled):
    return deepcopy(_assembled["healthcare"])


@pytest.fixture
def limited(_assembled):
    return deepcopy(_assembled["limited-real-property"])
