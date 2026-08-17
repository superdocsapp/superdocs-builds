from pathlib import Path

from app.gateway.audit import AuditLogger
from app.gateway.policy import load_gateway_policy
from app.gateway.sensitive import SensitiveAction, scan_sensitive_content


def test_sensitive_patterns_and_masking():
    result = scan_sensitive_content(
        "a@example.com 123-45-6789 sk_abcdefghijklmnop",
        action=SensitiveAction.MASK,
    )
    assert result.allowed
    assert "[REDACTED:email]" in result.content
    assert "[REDACTED:ssn]" in result.content
    assert "[REDACTED:api_key]" in result.content


def test_audit_hash_chain():
    logger = AuditLogger()
    first = logger.record(
        request_id="1", team="default", tool="chat",
        allowed=True, status_code=200, duration_ms=1,
    )
    second = logger.record(
        request_id="2", team="default", tool="export",
        allowed=False, status_code=403, duration_ms=2,
    )
    assert first.previous_hash == ""
    assert second.previous_hash == first.event_hash
    assert len(second.event_hash) == 64


def test_policy_file_loads():
    policy = load_gateway_policy(
        Path(__file__).parents[1] / "config" / "gateway_policy.yaml"
    )
    assert policy.tool_policy.is_allowed("upload")
    assert policy.tool_policy.is_allowed("chat")
    assert policy.sensitive_policy.enabled is True
    assert policy.quotas["default"] == 100
