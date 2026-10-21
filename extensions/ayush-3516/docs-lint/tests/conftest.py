"""Shared fixtures.

The fake server runs once for the whole session and is reset between tests. Starting a real HTTP
server per test would be slower without proving anything extra.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator

import httpx
import pytest

from docs_lint.superdocs.client import RetryPolicy, SuperDocsClient
from tests.fake_superdocs import FakeSuperDocs
from tests.fake_superdocs.server import DEFAULT_API_KEY

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fake() -> Iterator[FakeSuperDocs]:
    instance = FakeSuperDocs()
    with instance.serve() as base_url:
        instance.base_url = base_url  # type: ignore[attr-defined]
        yield instance


@pytest.fixture
def base_url(fake: FakeSuperDocs) -> str:
    """Base URL of the fake, with all state reset first."""
    url = fake.base_url  # type: ignore[attr-defined]
    httpx.post(f"{url}/_fake/reset").raise_for_status()
    return url


@pytest.fixture
def client(base_url: str) -> Iterator[SuperDocsClient]:
    """A client pointed at the fake, with instant retries so tests do not sleep."""
    with SuperDocsClient(
        api_key=DEFAULT_API_KEY,
        base_url=base_url,
        retry=RetryPolicy(max_attempts=4, base_delay=0.0, max_delay=0.0, jitter=False),
        sleep=lambda _seconds: None,
    ) as instance:
        yield instance


@pytest.fixture
def set_fault(base_url: str):
    def _set(**kwargs) -> None:
        httpx.post(f"{base_url}/_fake/fault", json=kwargs).raise_for_status()

    return _set


@pytest.fixture
def fake_state(base_url: str):
    def _state() -> dict:
        return httpx.get(f"{base_url}/_fake/state").json()

    return _state


def cassette(name: str) -> dict:
    """Load a response recorded from the live API."""
    return json.loads((FIXTURES / "cassettes" / f"{name}.json").read_text())


SAMPLE_DOC = """# Getting Started

We utilise the API in order to fetch results.

This paragraph is already fine and must not change.

```python
# code blocks are never linted for prose
value = utilise_this()
```

You can leverage the client for batch work.
"""
