"""A pytest fixture, available the moment `sdmock` is installed.

The container is the right answer for polyglot CI. This is the right answer for a Python
integrator: no Docker, no port to choose, no key, no fixture files to manage.

    def test_my_upload(superdocs_mock):
        client = MyClient(base_url=superdocs_mock.url, api_key="sk_test")
        ...

Registered through the `pytest11` entry point, so `pip install sdmock` is the whole setup.
The server starts once per session and its cursors are rewound between tests, so nothing
depends on test order.
"""

from __future__ import annotations

import pytest

from .testing import MockServer


@pytest.fixture(scope="session")
def superdocs_mock_server():
    """A SuperDocs mock on a real port for the whole session."""
    with MockServer() as server:
        yield server


@pytest.fixture()
def superdocs_mock(superdocs_mock_server):
    """The mock, rewound before each test.

    Use `.url` for the REST base URL and `.mcp_url` for the MCP endpoint. Select a
    recorded scenario with the `X-Mock-Scenario` header; `sdmock catalogue` lists them.
    """
    superdocs_mock_server.reset()
    return superdocs_mock_server
