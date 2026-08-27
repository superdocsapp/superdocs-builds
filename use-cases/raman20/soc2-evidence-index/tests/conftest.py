from __future__ import annotations

from pathlib import Path

import pytest

from soc2_index.catalog import load_catalog, load_sample_catalog
from soc2_index.ingest import walk
from soc2_index.map import apply
from soc2_index.paths import project_root
from soc2_index.validate import build_index

ROOT = project_root()
FIXTURES = ROOT / "fixtures"


@pytest.fixture
def sample_catalog():
    return load_sample_catalog()


@pytest.fixture
def full_catalog():
    return load_catalog()


def build_from(folder: Path, catalog, generated_at: str = "1970-01-01T00:00:00Z"):
    files = walk(folder)
    mapping = apply(catalog, files)
    index = build_index(catalog, mapping, "Cedar Harbor Labs", "2025-01-01/2025-12-31", generated_at)
    return index, files, mapping
