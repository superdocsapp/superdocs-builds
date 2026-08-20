"""`builds/statutory-statements/` is a codebase, not an installed package.

The directory name carries a hyphen on purpose - it is an application folder,
not an import path - so the importable package inside it is `statutory` and this
file is what puts it on `sys.path` for the suite. Nothing here imports from
`system/`, and `tests/test_isolation.py` fails the build if it ever does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent.parent

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
# tests/ carries a helper (`recorded.py`) that loads responses out of
# docs/evidence/. It is not a package, so its directory goes on the path too.
if str(APP_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(APP_ROOT / "tests"))


@pytest.fixture(scope="session")
def corpus() -> Path:
    return REPO_ROOT / "corpus"


@pytest.fixture(scope="session")
def config() -> Path:
    return APP_ROOT / "config"


@pytest.fixture(scope="session")
def evidence() -> Path:
    return REPO_ROOT / "docs" / "evidence"


@pytest.fixture(scope="session")
def rolled(corpus: Path, config: Path):
    from statutory.pipeline import prepare

    return prepare(corpus, config)
