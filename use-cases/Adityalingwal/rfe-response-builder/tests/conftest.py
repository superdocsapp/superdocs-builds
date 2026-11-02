import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.load_corpus import petition_sections, read_notice, read_petition
from engine.retrieve_petition_material import load_retrieval_config


@pytest.fixture(scope="session")
def notice_text():
    return read_notice(ROOT / "data" / "notice")


@pytest.fixture(scope="session")
def petition():
    return read_petition(ROOT / "data" / "petition")


@pytest.fixture(scope="session")
def sections(petition):
    return petition_sections(petition)


@pytest.fixture(scope="session")
def retrieval_config():
    return load_retrieval_config(ROOT / "config" / "retrieval.json")
