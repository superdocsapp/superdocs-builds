"""
Smoke test: drive the GENERATED Python client against the Prism mock server.
Proves the generated client is usable end-to-end — it builds a request from the
spec, calls the mock, and deserializes the response into the generated model.
No API key, no live service — Prism serves schema-valid examples.

Run: pytest tests/python  (with Prism mock up on SUPERDOCS_MOCK_URL)
"""
import os
import pytest

from superdocs_client import Configuration, ApiClient
from superdocs_client.api.users_api import UsersApi

MOCK_URL = os.environ.get("SUPERDOCS_MOCK_URL", "http://localhost:4010")


def test_get_current_user_profile_against_mock():
    cfg = Configuration(host=MOCK_URL, access_token="smoke-test-token")
    with ApiClient(cfg) as api_client:
        users = UsersApi(api_client)
        # GET /v1/users/me — a representative typed call through the client.
        profile = users.get_current_user_profile_v1_users_me_get()

    assert profile is not None
    # Prism returned a schema-valid example, so the generated model populated.
    assert hasattr(profile, "email"), "expected a typed user profile model"
    print(f"\nPython smoke OK — {MOCK_URL}/v1/users/me -> {type(profile).__name__}")
