"""Smoke test: the package imports and the toolchain (ruff/mypy/pytest) is wired.

Replaced by real behavioural tests as each floor phase lands; kept as a trivial
liveness check so the CI gate is green from commit one.
"""

from __future__ import annotations

import notion_review


def test_version_is_exposed() -> None:
    assert notion_review.__version__ == "0.1.0"
