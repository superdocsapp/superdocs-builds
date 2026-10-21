from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.backend.main import app
from app.backend.store import store


@pytest.fixture(autouse=True)
def reset_store():
    store.reset()
    yield
    store.reset()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def repo_root_str(repo_root):
    return str(repo_root)
