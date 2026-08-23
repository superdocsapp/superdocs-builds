"""No keys, no network — the whole suite.

`service/` is importable from the app root, which is where pytest runs, so
nothing here manipulates paths. An app that needs a path shim to test itself is
an app that will need one to run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer with a real key must not have a different test run — and
    must not spend an export operation by running the suite."""
    monkeypatch.setenv("SUPERDOCS_API_KEY", "")
