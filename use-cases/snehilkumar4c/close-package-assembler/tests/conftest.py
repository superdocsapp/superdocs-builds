"""Shared pytest fixtures for the whole suite.

Tests that need Postgres point at TEST_DATABASE_URL (falls back to a local default
matching the docker-compose service / local Homebrew Postgres used in development).
CI provides this via a postgres service container — see .github/workflows/ci.yml.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from core.idempotency import IdempotencyStore


@pytest.fixture(scope="session")
def vcr_cassette_dir() -> str:
    """Where pytest-recording (@pytest.mark.vcr) looks for/writes cassettes.
    Fixed to tests/fixtures/cassettes/ rather than the default per-test-module
    path, so test_prompt_injection.py's own cassette-existence check agrees
    with where pytest-recording actually reads from."""
    return str(Path(__file__).parent / "fixtures" / "cassettes")


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, object]:
    """pytest-recording defaults to record_mode="none" (playback-only) unless
    told otherwise -- a deliberate safety default so a normal test run never
    accidentally hits a real API. We tie recording permission to the same
    RECORD_LLM_CASSETTES=1 flag test_prompt_injection.py already gates on,
    rather than requiring a separate --record-mode CLI flag to remember.
    First real attempt at recording failed with a misleading "Connection
    error" that was actually vcrpy's CannotOverwriteExistingCassetteException
    (raised even with NO cassette present, because record_mode="none" refuses
    to record at all) -- our own broad exception handling in core/llm.py
    swallowed the real error type. Fixed here, not by loosening that handling.

    filter_headers is NOT optional: the first real recording (before this was
    added) captured the actual x-api-key header verbatim into the cassette
    file -- caught by grepping the recorded file for the key pattern before
    committing, not by any automatic protection. That cassette was deleted and
    re-recorded with this filter in place. Never commit a cassette without
    checking it first regardless -- this filter is defense in depth, not a
    substitute for that check."""
    return {
        "record_mode": "once" if os.environ.get("RECORD_LLM_CASSETTES") == "1" else "none",
        "filter_headers": ["x-api-key", "authorization"],
    }


@pytest.fixture
def test_dsn() -> str:
    return os.environ.get(
        "TEST_DATABASE_URL", "postgresql://localhost:5432/closepkg_test"
    )


@pytest.fixture
def idempotency_store(test_dsn: str) -> Iterator[IdempotencyStore]:
    """Truncates the table before AND after each test. Before, in case a prior
    manual/ad-hoc run (or a crashed prior test) left rows behind — this table is
    test/dev-only, so a full truncate is safe and is the only isolation guarantee
    strong enough to survive that. A prefix-based DELETE was tried first and missed
    exactly this case; see PROGRESS.md for the caught bug."""
    import psycopg

    store = IdempotencyStore(test_dsn)
    store.setup()
    with psycopg.connect(test_dsn) as conn:
        conn.execute("TRUNCATE idempotency_keys")
        conn.commit()
    yield store
    with psycopg.connect(test_dsn) as conn:
        conn.execute("TRUNCATE idempotency_keys")
        conn.commit()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """get_settings() is @lru_cache'd — clear it between tests so one test's env
    vars don't leak into the next."""
    from core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
