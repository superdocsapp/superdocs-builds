"""Test bootstrap: make the ``exhibit`` package importable and provide the
sample brief + evidence pile as fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exhibit.loader import load_evidence  # noqa: E402
from exhibit.order import EvidenceItem  # noqa: E402


@pytest.fixture()
def sample_brief() -> str:
    return (ROOT / "sample" / "brief" / "supporting_brief.md").read_text(encoding="utf-8")


@pytest.fixture()
def sample_items() -> list[EvidenceItem]:
    evidence_dir = ROOT / "sample" / "evidence"
    paths = sorted(str(p) for p in evidence_dir.iterdir())
    return load_evidence(paths)


@pytest.fixture()
def empty_brief() -> str:
    return "This application is supported by the documents attached to this brief."
