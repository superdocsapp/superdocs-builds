"""End to end: real ASGI app, every gate on, audit written and then verified.

The other suites test one gate each against a narrow policy. This one runs the
policy from PLAN.md §6 — allowlist, argument rules, content scan, quota and
audit all active — and drives a sequence of requests through the whole stack,
then asks the chain whether it still verifies.

Zero SuperDocs quota is consumed: the upstream is a fake transport.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import httpx

from gateway.audit import AuditLog, read_entries, verify_chain
from gateway.cli import main as cli_main
from tests.conftest import LEGAL_TOKEN, MKTG_TOKEN, FakeUpstream

CT = "application/json"
OK_RESULT = b'{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"done"}]}}'


def _call(tool: str, arguments: dict | None = None, rpc_id: int = 1) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": rpc_id,
            "params": {"name": tool, "arguments": arguments or {}},
        }
    ).encode()


def _rpc(method: str, rpc_id: int = 1) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "method": method, "id": rpc_id}).encode()


def _headers(token: str = LEGAL_TOKEN) -> dict[str, str]:
    return {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {token}"}


def _entries(path: Path) -> list[dict]:
    return [e for _, e in read_entries(path)]


def _make_docx(text: str) -> bytes:
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


# ──── The full journey ───────────────────────────────────────────────────


async def test_full_journey_and_chain_verifies(
    gw_full: httpx.AsyncClient,
    upstream: FakeUpstream,
    audit_path: Path,
) -> None:
    """Nine requests covering every decision the gateway can reach."""
    # 1 · allowed, billable, with argument rewrites applied
    upstream.respond(200, OK_RESULT)
    r = await gw_full.post(
        "/mcp",
        content=_call("chat_async", {"message": "Summarise the MSA", "model_tier": "standard"}),
        headers=_headers(),
    )
    assert r.status_code == 200

    # 2 · tool outside the team's allowlist
    r = await gw_full.post("/mcp", content=_call("archive_document"), headers=_headers())
    assert r.status_code == 403

    # 3 · the pre-signed URL hole, closed by default policy
    r = await gw_full.post("/mcp", content=_call("request_upload_url"), headers=_headers())
    assert r.status_code == 403

    # 4 · argument over the team's ceiling
    r = await gw_full.post(
        "/mcp", content=_call("chat_async", {"model_tier": "max"}), headers=_headers()
    )
    assert r.status_code == 403

    # 5 · PII in the prompt
    r = await gw_full.post(
        "/mcp",
        content=_call("chat_async", {"message": "email alice@corp.com the draft"}),
        headers=_headers(),
    )
    assert r.status_code == 403

    # 6 · an agent presenting its own credential
    upstream.respond(200, OK_RESULT)
    r = await gw_full.post(
        "/mcp",
        content=_call("get_job", {"job_id": "j1", "authorization": "Bearer sk_stolen"}),
        headers=_headers(),
    )
    assert r.status_code == 200

    # 7 · upstream failure — must not bill
    upstream.respond(500, b'{"error":"boom"}')
    r = await gw_full.post(
        "/mcp", content=_call("chat_async", {"message": "retry"}), headers=_headers()
    )
    assert r.status_code == 500

    # 8 · no credential at all
    r = await gw_full.post("/mcp", content=_call("chat_async"), headers={"Content-Type": CT})
    assert r.status_code == 401

    # 9 · tools/list, filtered to the team's permitted set
    upstream.respond(
        200,
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tools": [
                        {"name": "chat_async"},
                        {"name": "get_job"},
                        {"name": "archive_document"},
                        {"name": "request_upload_url"},
                    ]
                },
            }
        ).encode(),
    )
    r = await gw_full.post("/mcp", content=_rpc("tools/list"), headers=_headers())
    assert r.status_code == 200
    assert {t["name"] for t in r.json()["result"]["tools"]} == {"chat_async", "get_job"}

    # ── the log tells the whole story, and still verifies ──
    result = verify_chain(audit_path)
    assert result.ok, result.describe()
    assert result.entries == 9

    decisions = [e["decision"] for e in _entries(audit_path)]
    assert decisions == [
        "allowed",
        "denied_tool",
        "denied_tool",
        "denied_argument",
        "blocked_content",
        "allowed",
        "upstream_error",
        "unauthorized",
        "allowed",
    ]


# ──── What each entry actually records ───────────────────────────────────


async def test_allowed_entry_records_rewrites_and_billing(
    gw_full: httpx.AsyncClient, upstream: FakeUpstream, audit_path: Path
) -> None:
    upstream.respond(200, OK_RESULT)
    await gw_full.post(
        "/mcp", content=_call("chat_async", {"message": "hello"}), headers=_headers()
    )

    entry = _entries(audit_path)[0]
    assert entry["team"] == "legal"
    assert entry["tool"] == "chat_async"
    assert entry["decision"] == "allowed"
    assert entry["billed"] == 1
    assert entry["upstream_status"] == 200
    assert entry["latency_ms"] >= 0
    assert entry["resp_bytes"] > 0
    # Both the global rule and the team's tool-specific one fired.
    assert set(entry["arg_rewrites"]) == {
        "cross_session_memory=False",
        "approval_mode=ask_every_time",
    }


async def test_stripped_authorization_is_flagged(
    gw_full: httpx.AsyncClient, upstream: FakeUpstream, audit_path: Path
) -> None:
    """The bypass attempt is the entry worth alerting on, so it must be visible."""
    upstream.respond(200, OK_RESULT)
    await gw_full.post(
        "/mcp",
        content=_call("get_job", {"job_id": "j1", "authorization": "Bearer sk_stolen"}),
        headers=_headers(),
    )

    entry = _entries(audit_path)[0]
    assert entry["auth_stripped"] is True

    # And it never reached SuperDocs.
    forwarded = json.loads(upstream.requests[0].content)
    assert "authorization" not in forwarded["params"]["arguments"]


async def test_scan_hits_recorded_even_when_only_masked(
    gw_full: httpx.AsyncClient, upstream: FakeUpstream, audit_path: Path
) -> None:
    """Marketing masks rather than blocks — the match still belongs in the log."""
    upstream.respond(200, OK_RESULT)
    r = await gw_full.post(
        "/mcp",
        content=_call("chat_async", {"message": "ping bob@corp.com"}),
        headers=_headers(MKTG_TOKEN),
    )
    assert r.status_code == 200

    entry = _entries(audit_path)[0]
    assert entry["decision"] == "allowed"
    assert entry["scan_hits"] == ["pii_email"]


async def test_failed_call_bills_zero_and_refunds(
    gw_full: httpx.AsyncClient, upstream: FakeUpstream, audit_path: Path
) -> None:
    upstream.respond(200, OK_RESULT)
    await gw_full.post("/mcp", content=_call("chat_async", {"message": "a"}), headers=_headers())
    upstream.respond(503, b"upstream down")
    await gw_full.post("/mcp", content=_call("chat_async", {"message": "b"}), headers=_headers())

    entries = _entries(audit_path)
    assert entries[0]["billed"] == 1
    assert entries[1]["billed"] == 0
    assert entries[1]["decision"] == "upstream_error"

    # The refund means the third call still fits inside monthly_edits=3.
    for _ in range(2):
        upstream.respond(200, OK_RESULT)
        r = await gw_full.post(
            "/mcp", content=_call("chat_async", {"message": "c"}), headers=_headers()
        )
        assert r.status_code == 200

    r = await gw_full.post(
        "/mcp", content=_call("chat_async", {"message": "d"}), headers=_headers()
    )
    assert r.status_code == 429
    assert _entries(audit_path)[-1]["decision"] == "quota_exhausted"


# ──── The privacy property ───────────────────────────────────────────────


async def test_audit_never_contains_document_content(
    gw_full: httpx.AsyncClient, upstream: FakeUpstream, audit_path: Path
) -> None:
    """An audit log that quotes the documents it guards is a second copy of them.

    Every field carrying content is pushed through the gateway here — a prompt,
    an HTML export body, and the text inside a .docx — and none of it may appear
    in the log. What is recorded is the SHA-256 of the request.
    """
    secrets = ["ACQUISITION_CODENAME_ORCHID", "wilbur@acme-legal.example", "111-22-3333"]

    upstream.respond(200, OK_RESULT)
    await gw_full.post(
        "/mcp",
        content=_call("chat_async", {"message": f"Draft a memo about {secrets[0]}"}),
        headers=_headers(),
    )

    upstream.respond(200, OK_RESULT)
    await gw_full.post(
        "/mcp",
        content=_call("export_document", {"html": f"<p>{secrets[0]} is confidential</p>"}),
        headers=_headers(),
    )

    docx = base64.b64encode(_make_docx(f"Contact {secrets[1]} — SSN {secrets[2]}")).decode()
    await gw_full.post(
        "/mcp",
        content=_call("upload_document_base64", {"file_base64": docx}),
        headers=_headers(),
    )

    raw = audit_path.read_text()
    for secret in secrets:
        assert secret not in raw, f"audit log leaked {secret!r}"
    # Nor the base64 payload itself.
    assert docx[:64] not in raw

    # But the request IS pinned, by hash.
    entries = _entries(audit_path)
    assert all(len(e["payload_sha256"]) == 64 for e in entries)
    assert len({e["payload_sha256"] for e in entries}) == 3

    # And the block that stopped the upload is on the record, by rule name.
    assert entries[2]["decision"] == "blocked_content"
    assert set(entries[2]["scan_hits"]) == {"pii_email", "pii_ssn"}


# ──── Restart, and the operator CLI ──────────────────────────────────────


async def test_chain_continues_across_a_restart(
    upstream: FakeUpstream, full_policy, audit_path: Path
) -> None:
    """Two gateway lifetimes, one chain."""
    from gateway.quota import QuotaStore
    from tests.conftest import _make_gw

    for _ in range(2):
        async with _make_gw(
            upstream,
            full_policy,
            quota_store=QuotaStore.from_policy(full_policy),
            audit_log=AuditLog(audit_path, fsync=False),
        ) as client:
            upstream.respond(200, OK_RESULT)
            await client.post(
                "/mcp", content=_call("chat_async", {"message": "x"}), headers=_headers()
            )

    result = verify_chain(audit_path)
    assert result.ok
    assert result.entries == 2


async def test_cli_verify_passes_then_fails_after_tampering(
    gw_full: httpx.AsyncClient,
    upstream: FakeUpstream,
    audit_path: Path,
    capsys,
) -> None:
    """`gateway audit verify` is the deliverable — exit 0 clean, exit 1 tampered."""
    for _ in range(3):
        upstream.respond(200, OK_RESULT)
        await gw_full.post(
            "/mcp", content=_call("chat_async", {"message": "x"}), headers=_headers()
        )

    assert cli_main(["audit", "verify", str(audit_path)]) == 0
    assert "chain intact" in capsys.readouterr().out

    lines = audit_path.read_text().splitlines()
    entry = json.loads(lines[1])
    entry["billed"] = 0  # quietly un-bill a call
    lines[1] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    audit_path.write_text("\n".join(lines) + "\n")

    assert cli_main(["audit", "verify", str(audit_path)]) == 1
    assert "BROKEN at line 2" in capsys.readouterr().out


async def test_cli_stats_summarises_decisions(
    gw_full: httpx.AsyncClient, upstream: FakeUpstream, audit_path: Path, capsys
) -> None:
    upstream.respond(200, OK_RESULT)
    await gw_full.post("/mcp", content=_call("chat_async", {"message": "x"}), headers=_headers())
    await gw_full.post("/mcp", content=_call("archive_document"), headers=_headers())

    assert cli_main(["audit", "stats", str(audit_path)]) == 0
    out = capsys.readouterr().out
    assert "2 entries" in out
    assert "allowed" in out
    assert "denied_tool" in out
    assert "legal" in out


def test_cli_hash_token_matches_policy_hashing(capsys) -> None:
    from gateway.policy import hash_token

    assert cli_main(["hash-token", LEGAL_TOKEN]) == 0
    assert capsys.readouterr().out.strip() == hash_token(LEGAL_TOKEN)
