"""Shared test fixtures. No network, no API keys, no Google accounts.

Environment is pinned to non-secret test values before any app import so
nothing accidentally reaches a real service.
"""

import os

os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("SUPERDOCS_API_KEY", "sk_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")

import pytest


@pytest.fixture
def fake_token():
    """A TokenData-shaped dict the fake auth provider hands out."""
    return {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token",
        "expires_at": 9999999999,
        "email": "teacher@test.edu",
    }
