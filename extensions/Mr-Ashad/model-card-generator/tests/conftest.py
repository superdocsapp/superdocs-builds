"""Pytest configuration and test fixtures."""

import json
from pathlib import Path
import pytest

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def base_dir():
    return BASE_DIR


@pytest.fixture
def sample_manifest_path():
    return BASE_DIR / "sample_data" / "sample_manifest.json"


@pytest.fixture
def sample_eval_json_path():
    return BASE_DIR / "sample_data" / "sample_eval_results.json"


@pytest.fixture
def sample_eval_csv_path():
    return BASE_DIR / "sample_data" / "sample_eval_results.csv"


@pytest.fixture
def base_template_path():
    return BASE_DIR / "templates" / "base_card_template.md"
