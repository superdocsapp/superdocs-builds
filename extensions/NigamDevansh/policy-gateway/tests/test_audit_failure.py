"""Failing closed when the audit log cannot be written.

The gateway's claim is that every call is on the record. A storage fault must
therefore stop traffic rather than open a silent hole in the chain — and the
error has to name storage as the cause, because the caller cannot fix it and
needs to escalate to whoever can.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from gateway.audit import AuditLog, AuditWriteError, verify_chain
from gateway.proxy import Proxy
from gateway.quota import QuotaStore
from tests.conftest import LEGAL_TOKEN, FakeUpstream, _make_gw

CT = "application/json"
OK_RESULT = b'{"jsonrpc":"2.0","id":1,"result":{"content":[]}}'


def _call(tool: str, arguments: dict | None = None) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {"name": tool, "arguments": arguments or {}},
        }
    ).encode()


def _headers(token: str = LEGAL_TOKEN) -> dict[str, str]:
    return {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {token}"}


# ──── preflight ──────────────────────────────────────────────────────────


def test_preflight_passes_on_a_healthy_log(tmp_path: Path) -> None:
    AuditLog(tmp_path / "audit.jsonl", fsync=False).preflight()


def test_preflight_detects_a_missing_directory(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "data" / "audit.jsonl", fsync=False)
    (tmp_path / "data").rmdir()  # the volume went away under us

    with pytest.raises(AuditWriteError, match="volume mounted"):
        log.preflight()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the write bit")
def test_preflight_detects_a_read_only_directory(tmp_path: Path) -> None:
    d = tmp_path / "data"
    d.mkdir()
    log = AuditLog(d / "audit.jsonl", fsync=False)
    d.chmod(0o500)
    try:
        with pytest.raises(AuditWriteError, match="not writable"):
            log.preflight()
    finally:
        d.chmod(0o700)


# ──── the request path fails closed ──────────────────────────────────────


async def test_request_is_refused_when_the_log_is_unwritable(
    upstream: FakeUpstream, full_policy, tmp_path: Path
) -> None:
    """503, nothing forwarded, and the message routes the user to the right team."""
    data = tmp_path / "data"
    data.mkdir()
    audit = AuditLog(data / "audit.jsonl", fsync=False)

    async with _make_gw(
        upstream,
        full_policy,
        quota_store=QuotaStore.from_policy(full_policy),
        audit_log=audit,
    ) as client:
        data.rename(tmp_path / "gone")  # volume disappears mid-flight

        upstream.respond(200, OK_RESULT)
        r = await client.post(
            "/mcp", content=_call("chat_async", {"message": "hi"}), headers=_headers()
        )

    assert r.status_code == 503
    message = r.json()["error"]["message"]
    assert "storage fault" in message
    assert "platform team" in message
    assert "not a problem with your request" in message

    # Refused BEFORE forwarding: no call, and therefore no bill.
    assert upstream.requests == []


async def test_refusal_happens_before_quota_is_spent(
    upstream: FakeUpstream, full_policy, tmp_path: Path
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    audit = AuditLog(data / "audit.jsonl", fsync=False)
    quota = QuotaStore.from_policy(full_policy)

    async with _make_gw(upstream, full_policy, quota_store=quota, audit_log=audit) as client:
        data.rename(tmp_path / "gone")
        await client.post(
            "/mcp", content=_call("chat_async", {"message": "hi"}), headers=_headers()
        )

    tq = quota.get("legal")
    assert tq is not None
    assert tq.used == 0
    assert tq.reserved == 0


async def test_write_failure_after_forwarding_says_so(
    upstream: FakeUpstream, full_policy, tmp_path: Path, monkeypatch
) -> None:
    """The window preflight cannot close: the disk fills between check and write.

    The call may already have reached SuperDocs, so the error must not claim it
    did not happen.
    """
    audit = AuditLog(tmp_path / "audit.jsonl", fsync=False)

    def _full_disk(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    async with _make_gw(
        upstream,
        full_policy,
        quota_store=QuotaStore.from_policy(full_policy),
        audit_log=audit,
    ) as client:
        upstream.respond(200, OK_RESULT)
        monkeypatch.setattr(Path, "open", _full_disk)
        r = await client.post(
            "/mcp", content=_call("chat_async", {"message": "hi"}), headers=_headers()
        )

    assert r.status_code == 503
    message = r.json()["error"]["message"]
    assert "No space left on device" in message
    assert "may have completed" in message
    # It did reach upstream — which is exactly why the message is worded that way.
    assert len(upstream.requests) == 1


def test_failed_append_does_not_advance_the_chain(tmp_path: Path, monkeypatch) -> None:
    """A write that never landed must not become the `prev` of the next entry."""
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, fsync=False)
    log.append({"decision": "allowed", "seq": 0})
    head_before = log.head

    def _full_disk(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "open", _full_disk)
    with pytest.raises(AuditWriteError, match="No space left"):
        log.append({"decision": "allowed", "seq": 1})
    monkeypatch.undo()

    assert log.head == head_before
    log.append({"decision": "allowed", "seq": 2})

    result = verify_chain(path)
    assert result.ok, result.describe()
    assert result.entries == 2


# ──── startup ────────────────────────────────────────────────────────────


async def test_gateway_refuses_to_start_with_an_unwritable_log(tmp_path: Path) -> None:
    """Better to die at boot than come up healthy and 503 every request."""
    data = tmp_path / "data"
    data.mkdir()
    proxy = Proxy(
        upstream_url="https://upstream.test/mcp",
        client=httpx.AsyncClient(),
        audit_log=AuditLog(data / "audit.jsonl", fsync=False),
    )
    data.rename(tmp_path / "gone")

    with pytest.raises(AuditWriteError):
        await proxy.start()
