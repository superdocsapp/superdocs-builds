"""Live tests against the real SuperDocs MCP endpoint. Opt-in, and they cost money.

    RUN_LIVE_GATEWAY=1 uv run pytest -m live -s

Everything else in this suite runs against a fake transport and spends nothing.
This file is the exception, and it exists because a proxy that has only ever
talked to its own test double has not been shown to proxy anything.

`test_live_billed_chat_async` consumes roughly **one SuperDocs edit operation**
per run. It sends `approval_mode=ask_every_time`, so the job parks at
`awaiting_approval` and the test never approves it — the document is read and
reasoned about, but nothing is applied.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import time
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest

from gateway.app import create_app
from gateway.audit import AuditLog, read_entries, verify_chain
from gateway.policy import ArgRule, Policy, ScanConfig, TeamPolicy, hash_token
from gateway.proxy import Proxy
from gateway.quota import QuotaStore

pytestmark = pytest.mark.live

UPSTREAM = "https://api.superdocs.app/mcp"
TOKEN = "gw_live_test_token"
CT = "application/json"


def _api_key() -> str:
    """The real key, from the environment or the nearest .env.

    Never inlined, never logged. `load_policy` reads it the same way in
    production; this only widens the search so a developer does not have to
    export it by hand.
    """
    key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    if key:
        return key

    # This project's own .env only. An earlier revision also searched three
    # levels up, at the root of the monorepo this was developed in — a path
    # that means nothing in a standalone checkout and could pick up an
    # unrelated file on someone else's disk.
    here = Path(__file__).resolve()
    for candidate in (here.parents[1] / ".env",):
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "SUPERDOCS_API_KEY":
                return value.strip().strip("\"'")
    return ""


def _require_live() -> str:
    if os.environ.get("RUN_LIVE_GATEWAY") != "1":
        pytest.skip("set RUN_LIVE_GATEWAY=1 to run live tests (they consume quota)")
    key = _api_key()
    if not key:
        pytest.skip("SUPERDOCS_API_KEY is not set")
    return key


def _minimal_docx(paragraphs: list[str]) -> bytes:
    """A valid minimal OOXML package, built here rather than read from a fixture.

    The extension is meant to be `cp -r`-portable, so its tests do not reach
    into the parent repository for data.
    """
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return buf.getvalue()


def _live_policy(key: str) -> Policy:
    return Policy(
        upstream_url=UPSTREAM,
        upstream_key=key,
        default_deny_tools=frozenset({"request_upload_url", "request_download_url"}),
        default_scan=ScanConfig(
            rules=("pii_email", "pii_ssn", "secret_api_key", "injection_markers"),
            on_match="block",
        ),
        teams=(
            TeamPolicy(
                name="live",
                token_hash=hash_token(TOKEN),
                allow_tools=frozenset(
                    {"health", "upload_document_base64", "chat_async", "get_job"}
                ),
                # Known-good against the real API (see scripts/probe_superdocs.py):
                # forcing it proves gate ⑤ rewrites survive a real round trip.
                arg_rules=(
                    ("chat_async.approval_mode", ArgRule(mode="force", value="ask_every_time")),
                ),
                monthly_edits=2,
            ),
        ),
    )


@pytest.fixture
async def live_gw(tmp_path: Path):
    """A real gateway: fake nothing but the client socket into the ASGI app."""
    key = _require_live()
    policy = _live_policy(key)
    audit_path = tmp_path / "live-audit.jsonl"

    upstream_http = httpx.AsyncClient(timeout=120.0)
    proxy = Proxy(
        upstream_url=UPSTREAM,
        client=upstream_http,
        policy=policy,
        quota_store=QuotaStore.from_policy(policy),
        audit_log=AuditLog(audit_path, fsync=False),
    )
    app = create_app(proxy=proxy)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
        timeout=120.0,
    ) as client:
        client.audit_path = audit_path  # type: ignore[attr-defined]
        client.proxy = proxy  # type: ignore[attr-defined]
        yield client
    await upstream_http.aclose()


def _headers() -> dict[str, str]:
    # `Accept` is not optional: SuperDocs answers a request without it with 406.
    return {"Content-Type": CT, "Accept": CT, "Authorization": f"Bearer {TOKEN}"}


def _call(tool: str, arguments: dict, rpc_id: int = 1) -> bytes:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": rpc_id,
            "params": {"name": tool, "arguments": arguments},
        }
    ).encode()


def _entries(client: httpx.AsyncClient) -> list[dict]:
    return [e for _, e in read_entries(client.audit_path)]  # type: ignore[attr-defined]


def _result_text(payload: dict) -> str:
    """MCP wraps tool output in result.content[].text."""
    parts = payload.get("result", {}).get("content", [])
    return "\n".join(p.get("text", "") for p in parts if isinstance(p, dict))


def _extract_job_id(text: str) -> str:
    """Pull a job id out of the tool result, whether it is JSON or prose.

    The tool returns a text block; whether that block is JSON is not something
    this test should depend on, so it tries both and gives up quietly.
    """
    with contextlib.suppress(json.JSONDecodeError, AttributeError, TypeError):
        parsed = json.loads(text)
        if isinstance(parsed, dict) and parsed.get("job_id"):
            return str(parsed["job_id"])

    for token in text.replace('"', " ").replace(",", " ").split():
        if token.startswith("job_"):
            return token
    return ""


# ──── Free: connectivity, identity swap, filtering ───────────────────────


async def test_live_tools_list_is_filtered(live_gw: httpx.AsyncClient) -> None:
    r = await live_gw.post(
        "/mcp",
        content=json.dumps({"jsonrpc": "2.0", "method": "tools/list", "id": 1}).encode(),
        headers=_headers(),
    )
    assert r.status_code == 200, r.text

    names = {t["name"] for t in r.json()["result"]["tools"]}
    print(f"\n  tools visible to team 'live': {sorted(names)}")

    # Exactly the allowlist, and the pre-signed URL tools are gone.
    assert names == {"health", "upload_document_base64", "chat_async", "get_job"}
    assert "request_upload_url" not in names
    assert verify_chain(live_gw.audit_path).ok  # type: ignore[attr-defined]


async def test_live_health_call_and_auth_strip(live_gw: httpx.AsyncClient) -> None:
    """The agent's own credential is removed before the request leaves the gateway."""
    r = await live_gw.post(
        "/mcp",
        content=_call("health", {"authorization": "Bearer sk_not_a_real_key"}),
        headers=_headers(),
    )
    assert r.status_code == 200, r.text
    print(f"\n  health → {_result_text(r.json())[:200]}")

    entry = _entries(live_gw)[0]
    assert entry["decision"] == "allowed"
    assert entry["auth_stripped"] is True
    assert entry["billed"] == 0  # health is free
    assert entry["upstream_status"] == 200


async def test_live_denied_tool_never_leaves_the_gateway(live_gw: httpx.AsyncClient) -> None:
    r = await live_gw.post("/mcp", content=_call("request_upload_url", {}), headers=_headers())
    assert r.status_code == 403

    entry = _entries(live_gw)[0]
    assert entry["decision"] == "denied_tool"
    assert entry["upstream_status"] is None  # it was never sent


async def test_live_bad_token_is_rejected_locally(live_gw: httpx.AsyncClient) -> None:
    r = await live_gw.post(
        "/mcp",
        content=_call("health", {}),
        headers={"Content-Type": CT, "Accept": CT, "Authorization": "Bearer gw_wrong"},
    )
    assert r.status_code == 401
    assert _entries(live_gw)[0]["decision"] == "unauthorized"


# ──── Billed: the real edit path ─────────────────────────────────────────


async def test_live_billed_chat_async(live_gw: httpx.AsyncClient) -> None:
    """Upload → chat_async → get_job against the real API. Costs ~1 operation.

    Proves the two things a fake upstream cannot: that a forced argument is
    accepted by the real server, and that quota settles against a call that was
    genuinely billed.
    """
    session_id = f"gw-live-{uuid.uuid4().hex[:12]}"
    docx = _minimal_docx(
        [
            "MASTER SERVICES AGREEMENT",
            "Payment terms: Net 30 from date of invoice.",
            "Governing law: Delaware.",
        ]
    )

    # 1 · upload (free)
    r = await live_gw.post(
        "/mcp",
        content=_call(
            "upload_document_base64",
            {
                "session_id": session_id,
                "filename": "gateway-live-test.docx",
                "file_base64": base64.b64encode(docx).decode(),
                "open_mode": "replace",
            },
        ),
        headers=_headers(),
    )
    assert r.status_code == 200, f"upload failed: {r.text[:800]}"
    print(f"\n  upload → {_result_text(r.json())[:300]}")

    quota = live_gw.proxy._quota.get("live")  # type: ignore[attr-defined]
    assert quota.used == 0, "upload must not bill"

    # 2 · chat_async — THIS BILLS
    r = await live_gw.post(
        "/mcp",
        content=_call(
            "chat_async",
            {
                "session_id": session_id,
                "message": (
                    "In the section stating payment terms, replace the exact text "
                    "'Net 30' with 'Net 45'. Change nothing else."
                ),
                "response_mode": "compact",
            },
        ),
        headers=_headers(),
    )
    assert r.status_code == 200, f"chat_async failed: {r.text[:800]}"
    text = _result_text(r.json())
    print(f"  chat_async → {text[:300]}")

    # The forced approval_mode reached the wire and was accepted.
    chat_entry = _entries(live_gw)[1]
    assert "approval_mode=ask_every_time" in chat_entry["arg_rewrites"]
    assert chat_entry["decision"] == "allowed"
    assert chat_entry["billed"] == 1
    assert quota.used == 1, "a successful chat must settle exactly one unit"
    assert quota.reserved == 0

    # 3 · get_job (free) — poll briefly; the job parks at awaiting_approval
    # and we deliberately never approve it.
    job_id = _extract_job_id(text)
    if job_id:
        deadline = time.time() + 45
        status = ""
        while time.time() < deadline:
            r = await live_gw.post(
                "/mcp", content=_call("get_job", {"job_id": job_id}), headers=_headers()
            )
            assert r.status_code == 200, r.text
            status = _result_text(r.json())
            print(f"  get_job → {status[:160]}")
            if any(s in status for s in ("awaiting_approval", "completed", "failed")):
                break
            time.sleep(5)
        assert status, "get_job returned nothing"
        assert quota.used == 1, "polling a job must not bill"

    # 4 · quota is now 1 of 2; the chain covering all of it verifies
    result = verify_chain(live_gw.audit_path)  # type: ignore[attr-defined]
    assert result.ok, result.describe()
    print(f"  audit: {result.describe()}")


async def test_live_quota_ceiling_is_enforced(live_gw: httpx.AsyncClient) -> None:
    """Drive the team to its limit and confirm the gateway stops it locally.

    monthly_edits=2, so this costs at most 2 operations and the third request
    is refused without ever reaching SuperDocs.
    """
    session_id = f"gw-live-{uuid.uuid4().hex[:12]}"
    docx = _minimal_docx(["Quota ceiling probe.", "Payment terms: Net 30."])

    r = await live_gw.post(
        "/mcp",
        content=_call(
            "upload_document_base64",
            {
                "session_id": session_id,
                "filename": "quota-probe.docx",
                "file_base64": base64.b64encode(docx).decode(),
                "open_mode": "replace",
            },
        ),
        headers=_headers(),
    )
    assert r.status_code == 200, f"upload failed: {r.text[:800]}"

    quota = live_gw.proxy._quota.get("live")  # type: ignore[attr-defined]
    for i in range(2):
        r = await live_gw.post(
            "/mcp",
            content=_call(
                "chat_async",
                {
                    "session_id": session_id,
                    "message": f"Summarise this document in one sentence. (probe {i})",
                    "response_mode": "compact",
                },
            ),
            headers=_headers(),
        )
        assert r.status_code == 200, f"chat {i} failed: {r.text[:600]}"

    assert quota.used == 2

    before = len(_entries(live_gw))
    r = await live_gw.post(
        "/mcp",
        content=_call(
            "chat_async",
            {"session_id": session_id, "message": "one more", "response_mode": "compact"},
        ),
        headers=_headers(),
    )
    assert r.status_code == 429
    print("\n  third call refused locally:", r.json()["error"]["message"])

    last = _entries(live_gw)[-1]
    assert len(_entries(live_gw)) == before + 1
    assert last["decision"] == "quota_exhausted"
    assert last["upstream_status"] is None
    assert verify_chain(live_gw.audit_path).ok  # type: ignore[attr-defined]
