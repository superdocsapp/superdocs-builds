from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"
EXPECTED_RESULTS_PATH = FIXTURES_DIR / "expected_results.json"

# Matches expected_results.json's evaluation_assumptions.reference_evaluation_date.
# Tests run without a live model key or wall-clock dependency, so this
# reference date is fixed rather than read from `date.today()`.
REFERENCE_EVALUATION_DATE = date(2025, 8, 6)


@pytest.fixture(scope="session")
def expected_results() -> dict:
    with open(EXPECTED_RESULTS_PATH, encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def expected_cases(expected_results: dict) -> list[dict]:
    return expected_results["cases"]


@pytest.fixture(scope="session")
def reference_date() -> date:
    return REFERENCE_EVALUATION_DATE


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT
