"""
Shared pytest fixtures for the claims generator test suite.
"""
import os
import pytest


@pytest.fixture(autouse=True, scope="session")
def clear_proxy_env():
    """
    Remove proxy environment variables that httpx cannot parse (e.g. socks5h://).
    These may be present in CI / containerised environments but are not valid
    httpx proxy schemes, so they cause AsyncClient() to raise on instantiation.
    """
    for var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy",
                "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy"):
        os.environ.pop(var, None)
