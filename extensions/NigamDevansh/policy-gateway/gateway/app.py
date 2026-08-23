from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.responses import Response

from gateway.audit import AuditLog
from gateway.policy import load_policy
from gateway.proxy import Proxy
from gateway.quota import QuotaStore
from gateway.settings import get_settings


def build_proxy() -> Proxy:
    """Assemble the proxy the way a deployment does.

    No policy file → transparent passthrough. That is Milestone 1's behaviour
    and remains a supported mode: it lets someone put the gateway in the path
    and confirm nothing breaks *before* turning on enforcement.
    """
    settings = get_settings()
    policy_path = Path(settings.policy_path)

    if not policy_path.exists():
        return Proxy(upstream_url=settings.upstream_url)

    # `docker compose up` with no policy.yml on the host creates a DIRECTORY at
    # the bind-mount target. Falling back to passthrough here would be the
    # dangerous reading — the operator clearly intended enforcement, and a
    # gateway that quietly enforces nothing is worse than one that will not
    # start. So: refuse, and say exactly what to do about it.
    if not policy_path.is_file():
        raise RuntimeError(
            f"{policy_path.resolve()} is not a file. Docker creates a directory "
            f"at a bind-mount target when the host path is missing — run "
            f"`rmdir {policy_path}` then `cp policy.yml.example policy.yml`. "
            f"To run without enforcement, remove the policy.yml volume instead."
        )

    policy = load_policy(str(policy_path))
    return Proxy(
        upstream_url=policy.upstream_url,
        policy=policy,
        quota_store=QuotaStore.from_policy(policy),
        audit_log=AuditLog(settings.audit_log_path),
    )


def create_app(proxy: Proxy | None = None) -> FastAPI:
    _proxy = proxy if proxy is not None else build_proxy()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await _proxy.start()
        _app.state.proxy = _proxy
        yield
        await _proxy.stop()

    app = FastAPI(
        title="policy-gateway",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.post("/mcp")
    @app.post("/mcp/")
    async def forward_mcp(request: Request) -> Response:
        return await _proxy.forward(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
