from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from gateway.app import create_app
from gateway.audit import AuditLog
from gateway.policy import ArgRule, Policy, ScanConfig, TeamPolicy, hash_token
from gateway.proxy import Proxy
from gateway.quota import QuotaStore

LEGAL_TOKEN = "gw_legal_token"
MKTG_TOKEN = "gw_mktg_token"
UPSTREAM_KEY = "sk_test_upstream"


class FakeUpstream(httpx.AsyncBaseTransport):
    """Test double that records requests and replays queued responses."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self._queue: list[httpx.Response | Exception] = []

    def respond(
        self,
        status: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> FakeUpstream:
        h = {"content-type": "application/json", **(headers or {})}
        self._queue.append(httpx.Response(status, content=body, headers=h))
        return self

    def error(self, exc: Exception) -> FakeUpstream:
        self._queue.append(exc)
        return self

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._queue:
            item = self._queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return httpx.Response(502, content=b"FakeUpstream: no response queued")


@pytest.fixture
def upstream() -> FakeUpstream:
    return FakeUpstream()


@pytest.fixture
async def gw(upstream: FakeUpstream):
    """Test client pointing at a policy-free gateway (transparent passthrough)."""
    upstream_http = httpx.AsyncClient(transport=upstream)
    proxy = Proxy(upstream_url="https://upstream.test/mcp", client=upstream_http)
    app = create_app(proxy=proxy)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        yield client
    await upstream_http.aclose()


@pytest.fixture
def policy() -> Policy:
    return Policy(
        upstream_url="https://upstream.test/mcp",
        upstream_key=UPSTREAM_KEY,
        default_deny_tools=frozenset({"request_upload_url", "request_download_url"}),
        teams=(
            TeamPolicy(
                name="legal",
                token_hash=hash_token(LEGAL_TOKEN),
                allow_tools=frozenset({"chat_async", "get_job", "health", "export_document"}),
                deny_tools=frozenset(),
            ),
            TeamPolicy(
                name="marketing",
                token_hash=hash_token(MKTG_TOKEN),
                allow_tools=frozenset({"*"}),
                deny_tools=frozenset({"archive_document"}),
            ),
        ),
    )


@pytest.fixture
async def gw_policy(upstream: FakeUpstream, policy: Policy):
    """Test client pointing at a policy-enforced gateway."""
    async with _make_gw(upstream, policy) as client:
        yield client


def _make_gw(
    upstream: FakeUpstream,
    policy: Policy,
    quota_store: QuotaStore | None = None,
    audit_log: AuditLog | None = None,
):
    """Build a test client with the given policy."""
    import contextlib

    @contextlib.asynccontextmanager
    async def _ctx():
        upstream_http = httpx.AsyncClient(transport=upstream)
        proxy = Proxy(
            upstream_url="https://upstream.test/mcp",
            client=upstream_http,
            policy=policy,
            quota_store=quota_store,
            audit_log=audit_log,
        )
        app = create_app(proxy=proxy)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://gateway.test",
        ) as client:
            yield client
        await upstream_http.aclose()

    return _ctx()


@pytest.fixture
def policy_with_args() -> Policy:
    return Policy(
        upstream_url="https://upstream.test/mcp",
        upstream_key=UPSTREAM_KEY,
        default_deny_tools=frozenset(),
        default_arg_rules=(
            ("cross_session_memory", ArgRule(mode="force", value=False)),
            ("archive_document.force", ArgRule(mode="deny", value=True)),
        ),
        teams=(
            TeamPolicy(
                name="legal",
                token_hash=hash_token(LEGAL_TOKEN),
                allow_tools=frozenset({"*"}),
                arg_rules=(
                    ("chat_async.approval_mode", ArgRule(mode="force", value="ask_every_time")),
                    ("chat_async.model_tier", ArgRule(mode="max", value="pro")),
                ),
            ),
        ),
    )


@pytest.fixture
async def gw_args(upstream: FakeUpstream, policy_with_args: Policy):
    async with _make_gw(upstream, policy_with_args) as client:
        yield client


@pytest.fixture
def policy_with_scan() -> Policy:
    return Policy(
        upstream_url="https://upstream.test/mcp",
        upstream_key=UPSTREAM_KEY,
        default_deny_tools=frozenset(),
        default_scan=ScanConfig(
            rules=("pii_email", "pii_ssn", "secret_api_key", "injection_markers"),
            on_match="block",
        ),
        teams=(
            TeamPolicy(
                name="legal",
                token_hash=hash_token(LEGAL_TOKEN),
                allow_tools=frozenset({"*"}),
            ),
            TeamPolicy(
                name="marketing",
                token_hash=hash_token(MKTG_TOKEN),
                allow_tools=frozenset({"*"}),
                scan_on_match="mask",
            ),
        ),
    )


@pytest.fixture
async def gw_scan(upstream: FakeUpstream, policy_with_scan: Policy):
    async with _make_gw(upstream, policy_with_scan) as client:
        yield client


@pytest.fixture
def policy_with_quota() -> Policy:
    return Policy(
        upstream_url="https://upstream.test/mcp",
        upstream_key=UPSTREAM_KEY,
        default_deny_tools=frozenset(),
        teams=(
            TeamPolicy(
                name="legal",
                token_hash=hash_token(LEGAL_TOKEN),
                allow_tools=frozenset({"*"}),
                monthly_edits=5,
            ),
            TeamPolicy(
                name="marketing",
                token_hash=hash_token(MKTG_TOKEN),
                allow_tools=frozenset({"*"}),
            ),
        ),
    )


@pytest.fixture
def quota_store(policy_with_quota: Policy) -> QuotaStore:
    return QuotaStore.from_policy(policy_with_quota)


@pytest.fixture
async def gw_quota(upstream: FakeUpstream, policy_with_quota: Policy, quota_store: QuotaStore):
    async with _make_gw(upstream, policy_with_quota, quota_store=quota_store) as client:
        yield client


# ──── Every gate switched on, for the end-to-end suite ───────────────────


@pytest.fixture
def audit_path(tmp_path: Path) -> Path:
    return tmp_path / "audit.jsonl"


@pytest.fixture
def audit_log(audit_path: Path) -> AuditLog:
    # fsync off: these tests write hundreds of entries and never survive a
    # power cut. Production keeps the default on.
    return AuditLog(audit_path, fsync=False)


@pytest.fixture
def full_policy() -> Policy:
    """The policy from PLAN.md §6 — every gate active at once."""
    return Policy(
        upstream_url="https://upstream.test/mcp",
        upstream_key=UPSTREAM_KEY,
        default_deny_tools=frozenset({"request_upload_url", "request_download_url"}),
        default_arg_rules=(
            ("cross_session_memory", ArgRule(mode="force", value=False)),
            ("archive_document.force", ArgRule(mode="deny", value=True)),
        ),
        default_scan=ScanConfig(
            rules=("pii_email", "pii_ssn", "secret_api_key", "injection_markers"),
            on_match="block",
        ),
        teams=(
            TeamPolicy(
                name="legal",
                token_hash=hash_token(LEGAL_TOKEN),
                allow_tools=frozenset(
                    {"chat_async", "get_job", "upload_document_base64", "export_document"}
                ),
                arg_rules=(
                    ("chat_async.approval_mode", ArgRule(mode="force", value="ask_every_time")),
                    ("chat_async.model_tier", ArgRule(mode="max", value="pro")),
                ),
                monthly_edits=3,
            ),
            TeamPolicy(
                name="marketing",
                token_hash=hash_token(MKTG_TOKEN),
                allow_tools=frozenset({"*"}),
                scan_on_match="mask",
                monthly_edits=50,
            ),
        ),
    )


@pytest.fixture
async def gw_full(upstream: FakeUpstream, full_policy: Policy, audit_log: AuditLog):
    async with _make_gw(
        upstream,
        full_policy,
        quota_store=QuotaStore.from_policy(full_policy),
        audit_log=audit_log,
    ) as client:
        yield client
