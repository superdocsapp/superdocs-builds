"""
conftest.py -- test wiring shared by test_v2_api.py.

Two substitutions from the real app, both via FastAPI's dependency_overrides
(never monkeypatching internals):
  1. db.get_session  -> an in-memory SQLite engine (StaticPool, single
     shared connection) instead of pgserver/Postgres. Fast, no external
     process, fresh schema per test function.
  2. main.get_client  -> FakeSuperDocsClient (see fakes.py) instead of a
     real SuperDocsClient. No network calls, no API key required.

This keeps main.py itself completely unmodified for testing -- it never
knows it isn't talking to real Postgres or a real SuperDocs account.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import db
import main
from tests.fakes import FakeSuperDocsClient


@pytest.fixture()
def fake_client():
    return FakeSuperDocsClient()


@pytest.fixture()
def client(fake_client, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def get_session_override():
        with Session(engine) as session:
            yield session

    def get_client_override():
        return fake_client

    # The app's startup event calls db.init_db() directly (not through a
    # Depends-injected session), which would otherwise try to spin up a
    # real embedded pgserver -- no-op it out for tests.
    monkeypatch.setattr(db, "init_db", lambda: None)

    main.app.dependency_overrides[db.get_session] = get_session_override
    main.app.dependency_overrides[main.get_client] = get_client_override

    with TestClient(main.app) as test_client:
        yield test_client

    main.app.dependency_overrides.clear()
