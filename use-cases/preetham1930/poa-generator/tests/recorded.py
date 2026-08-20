"""Recorded SuperDocs responses, replayed. No key, no network, no invention.

Everything here comes out of `docs/evidence/`, which was captured on 2026-08-09
against the live API and saved with `redemption_id` stripped. The failure-class
tests are driven by those recordings rather than by hand-written HTML, because
the point is that these three failures are things the product actually did.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
REVERIFY = REPO_ROOT / "docs" / "evidence" / "2026-08-09-superdocs-reverify"
GATE = REPO_ROOT / "docs" / "evidence" / "2026-08-09-gate-and-templates"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_back_html(name: str) -> str:
    """`html` from a recorded GET /v1/documents/{id}?include_html=true."""
    return load(REVERIFY / f"{name}.json")["html"]


def gate_job(name: str) -> dict[str, Any]:
    return load(GATE / f"gate-job-{name}.json")


def targeted_edit_response() -> dict[str, Any]:
    return load(REVERIFY / "A-targeted-edit.response.json")


def append_response() -> dict[str, Any]:
    return load(REVERIFY / "C-append-structural.response.json")
