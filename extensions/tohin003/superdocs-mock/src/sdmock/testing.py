"""Run the mock from inside a test process.

The container is the right answer for polyglot CI; this is the right answer for a Python
integrator, who gets a real HTTP server on a real port with no Docker, no key and no
fixture files to manage:

    from sdmock.testing import MockServer

    with MockServer() as mock:
        client = MyClient(base_url=mock.url, api_key="sk_test")
        ...                                 # or point an MCP client at mock.mcp_url

A real socket rather than an ASGI shim, deliberately: integrations break on things a
transport shim papers over -- connection reuse, streaming, header casing, timeouts. A mock
that only works in-process would hide exactly the failures it exists to catch.
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import closing
from pathlib import Path
from types import TracebackType
from typing import Any

from .replay import Library


def free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MockServer:
    """A SuperDocs mock on a real port, started and stopped by a context manager."""

    def __init__(
        self,
        *,
        port: int | None = None,
        host: str = "127.0.0.1",
        cassettes: Path | None = None,
        require_auth: bool | None = None,
        startup_timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port or free_port()
        self.cassettes = cassettes
        self.require_auth = require_auth
        self.startup_timeout = startup_timeout
        self._server: Any = None
        self._thread: threading.Thread | None = None
        self.startup_seconds: float | None = None

    # ---------------------------------------------------------------- addresses

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def mcp_url(self) -> str:
        return f"{self.url}/mcp/"

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> "MockServer":
        import os

        import uvicorn

        from .app import create_app

        if self.require_auth is not None:
            os.environ["SDMOCK_REQUIRE_AUTH"] = "true" if self.require_auth else "false"
            # app reads the flag at import time, so re-read it for an in-process server
            from . import app as app_module

            app_module.REQUIRE_AUTH = self.require_auth

        began = time.perf_counter()
        library = Library(directory=self.cassettes) if self.cassettes else None
        config = uvicorn.Config(
            create_app(library),
            host=self.host,
            port=self.port,
            log_level="error",
            access_log=False,
            lifespan="off",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        deadline = time.perf_counter() + self.startup_timeout
        while time.perf_counter() < deadline:
            if getattr(self._server, "started", False):
                self.startup_seconds = time.perf_counter() - began
                return self
            time.sleep(0.005)
        raise TimeoutError(
            f"sdmock did not come up on {self.url} within {self.startup_timeout}s"
        )

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._server = None
        self._thread = None

    def __enter__(self) -> "MockServer":
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    # ---------------------------------------------------------------- helpers

    def reset(self, scenario: str | None = None, run: str | None = None) -> None:
        """Rewind cursors so tests do not depend on each other's order."""
        import urllib.parse
        import urllib.request

        query = {k: v for k, v in (("scenario", scenario), ("run", run)) if v}
        url = f"{self.url}/__sdmock__/reset"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        urllib.request.urlopen(url, timeout=5).read()


def pytest_fixture_source() -> str:
    """The fixture an integrator pastes into their own conftest.py."""
    return (
        "import pytest\n"
        "from sdmock.testing import MockServer\n\n"
        "@pytest.fixture(scope='session')\n"
        "def superdocs_mock():\n"
        "    with MockServer() as mock:\n"
        "        yield mock\n"
    )
