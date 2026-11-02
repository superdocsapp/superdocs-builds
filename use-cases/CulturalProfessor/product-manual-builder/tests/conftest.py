from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = PROJECT_ROOT / "spec" / "halyard_m1.yaml"


@pytest.fixture(scope="session")
def spec():
    from manualbuilder.spec import load_spec

    return load_spec(SPEC_PATH)
