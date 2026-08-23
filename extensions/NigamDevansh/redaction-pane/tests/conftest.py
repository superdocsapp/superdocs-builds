"""No keys, no network, no Word — the whole suite.

`service/` is importable from the extension root, which is where pytest runs, so
nothing here manipulates paths. That is a property worth keeping: an app that
needs a path shim to test itself is an app that will need one to run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Vendored beside the tests, not read from a repository root. This project
# ships as a standalone pull request, so it may not assume anything exists
# outside its own folder — the same reason `_portable/` holds a copy of the
# shared client rather than importing it.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "superdocs_responses"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """A developer with real keys must not have a different test run.

    The analyst learned this the expensive way: a suite that read `.env` spent a
    live quota on a machine that had one and passed on CI that did not.
    """
    for name in ("SUPERDOCS_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(name, "")


@pytest.fixture
def store(tmp_path: Path):
    from service.store import Store

    made = Store(tmp_path / "redaction.db")
    made.setup()
    return made
