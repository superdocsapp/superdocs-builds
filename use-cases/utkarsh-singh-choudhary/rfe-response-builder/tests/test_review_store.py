"""
Tests for webapp/review_store.py -- proves review-session state is
visible across separate ReviewSessionStore instances (standing in for
separate gunicorn worker processes sharing the same SQLite file), and
that TTL pruning and deletion behave correctly.
"""
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "webapp"))

from review_store import ReviewSessionStore  # noqa: E402


@dataclass
class FakeSession:
    case_id: str
    items: list


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "review_sessions.sqlite3")


def _url(db_path):
    return f"sqlite:///{db_path}"


def test_put_and_get_roundtrip(db_path):
    store = ReviewSessionStore(url=_url(db_path))
    session = FakeSession(case_id="CASE-1", items=[1, 2, 3])
    store.put("rid-1", session)
    retrieved = store.get("rid-1")
    assert retrieved.case_id == "CASE-1"
    assert retrieved.items == [1, 2, 3]


def test_visible_across_separate_store_instances(db_path):
    """Simulates two different gunicorn worker processes sharing one
    SQLite file -- a session written by one instance must be readable
    from another."""
    store_a = ReviewSessionStore(url=_url(db_path))
    store_b = ReviewSessionStore(url=_url(db_path))

    store_a.put("rid-2", FakeSession(case_id="CASE-2", items=[]))
    retrieved = store_b.get("rid-2")
    assert retrieved is not None
    assert retrieved.case_id == "CASE-2"


def test_missing_review_id_returns_none(db_path):
    store = ReviewSessionStore(url=_url(db_path))
    assert store.get("does-not-exist") is None


def test_delete_removes_session(db_path):
    store = ReviewSessionStore(url=_url(db_path))
    store.put("rid-3", FakeSession(case_id="CASE-3", items=[]))
    store.delete("rid-3")
    assert store.get("rid-3") is None


def test_delete_is_visible_across_instances(db_path):
    store_a = ReviewSessionStore(url=_url(db_path))
    store_b = ReviewSessionStore(url=_url(db_path))
    store_a.put("rid-4", FakeSession(case_id="CASE-4", items=[]))
    store_b.delete("rid-4")
    assert store_a.get("rid-4") is None


def test_expired_sessions_are_pruned_on_next_put(db_path):
    store = ReviewSessionStore(url=_url(db_path), ttl_s=0)
    store.put("rid-5", FakeSession(case_id="CASE-5", items=[]))
    time.sleep(0.01)
    # A second put triggers pruning; rid-5 is already past its (zero) TTL.
    store.put("rid-6", FakeSession(case_id="CASE-6", items=[]))
    assert store.get("rid-5") is None
    assert store.get("rid-6") is not None


def test_backend_property_reports_sqlite(db_path):
    store = ReviewSessionStore(url=_url(db_path))
    assert store.backend == "sqlite"


def test_postgres_url_scheme_is_normalized_for_psycopg2():
    from review_store import _normalize_url
    assert _normalize_url("postgres://user:pw@host:5432/dbname") == \
        "postgresql+psycopg2://user:pw@host:5432/dbname"
    # Already-correct URLs pass through unchanged.
    assert _normalize_url("postgresql+psycopg2://user:pw@host/dbname") == \
        "postgresql+psycopg2://user:pw@host/dbname"


def test_resolve_engine_url_prefers_review_store_url_env(monkeypatch):
    from review_store import _resolve_engine_url
    monkeypatch.setenv("REVIEW_STORE_URL", "postgresql+psycopg2://a/b")
    monkeypatch.setenv("DATABASE_URL", "postgres://c/d")
    assert _resolve_engine_url() == "postgresql+psycopg2://a/b"


def test_resolve_engine_url_falls_back_to_database_url_env(monkeypatch):
    from review_store import _resolve_engine_url
    monkeypatch.delenv("REVIEW_STORE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://c/d")
    assert _resolve_engine_url() == "postgresql+psycopg2://c/d"


def test_resolve_engine_url_defaults_to_local_sqlite(monkeypatch):
    from review_store import _resolve_engine_url
    monkeypatch.delenv("REVIEW_STORE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _resolve_engine_url().startswith("sqlite:///")
