"""`build_proxy` — how a deployment assembles itself from settings on disk."""

from __future__ import annotations

from pathlib import Path

import pytest

from gateway.app import build_proxy
from gateway.policy import hash_token
from gateway.settings import get_settings

POLICY = """
version: 1
upstream:
  url: https://upstream.test/mcp
  key_env: BOOTSTRAP_KEY
defaults:
  deny_tools: [request_upload_url]
teams:
  legal:
    token_hash: "{h}"
    allow_tools: [chat_async]
    quota: {{ monthly_edits: 7 }}
"""


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_no_policy_file_means_passthrough(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GATEWAY_POLICY_PATH", "policy.yml")
    proxy = build_proxy()
    assert proxy._policy is None
    assert proxy._audit is None


def test_policy_file_wires_quota_and_audit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOOTSTRAP_KEY", "sk_bootstrap")
    monkeypatch.setenv("GATEWAY_POLICY_PATH", "policy.yml")
    monkeypatch.setenv("GATEWAY_AUDIT_LOG_PATH", "data/audit.jsonl")
    Path("policy.yml").write_text(POLICY.format(h=hash_token("gw_x")))

    proxy = build_proxy()

    assert proxy._policy is not None
    assert proxy._policy.upstream_key == "sk_bootstrap"
    assert proxy._audit is not None
    quota = proxy._quota.get("legal")
    assert quota is not None
    assert quota.monthly_limit == 7


def test_a_directory_where_the_policy_should_be_refuses_to_start(
    tmp_path: Path, monkeypatch
) -> None:
    """The `docker compose up` footgun: a missing host file becomes a directory.

    Silently falling back to passthrough would mean a gateway that enforces
    nothing while looking healthy.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GATEWAY_POLICY_PATH", "policy.yml")
    Path("policy.yml").mkdir()

    with pytest.raises(RuntimeError, match="is not a file"):
        build_proxy()
