"""FastAPI auth dependencies.

`require_tenant` turns a bearer API key into a TenantContext. `require_admin`
guards tenant provisioning with the ADMIN_API_KEY. Failures are generic 401s so
we never reveal whether a key merely exists.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.context import TenantContext
from app.auth.hashing import hash_api_key, verify_admin_key
from app.config import Settings, get_settings
from app.db.repositories import TenantRepository
from app.db.session import get_session
from app.logging import tenant_id_ctx

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or missing API key.",
    headers={"WWW-Authenticate": "Bearer"},
)


bearer_scheme = HTTPBearer(auto_error=False)


def _extract_bearer(credentials: HTTPAuthorizationCredentials | None) -> str:
    if not credentials:
        raise _UNAUTHORIZED
    return credentials.credentials.strip()


async def require_tenant(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> TenantContext:
    token = _extract_bearer(credentials)
    repo = TenantRepository(session)
    api_key = await repo.get_active_key_by_hash(hash_api_key(token))
    if api_key is None:
        raise _UNAUTHORIZED
    ctx = TenantContext(tenant_id=api_key.tenant_id, api_key_id=api_key.id)
    # Bind tenant to the log context so every downstream log line is attributable.
    tenant_id_ctx.set(str(ctx.tenant_id))
    return ctx


async def require_admin(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    token = _extract_bearer(credentials)
    if not verify_admin_key(token, settings.admin_api_key):
        raise _UNAUTHORIZED
