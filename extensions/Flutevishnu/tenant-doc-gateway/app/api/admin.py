"""Admin endpoints: tenant provisioning.

Guarded by ADMIN_API_KEY. This is how a new end-customer (tenant) and its first
API key get created — a data operation, not a code change.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TenantCreateRequest, TenantCreateResponse
from app.auth.dependencies import require_admin
from app.auth.hashing import generate_api_key, hash_api_key, key_prefix
from app.db.repositories import TenantRepository
from app.db.session import get_session

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/tenants", response_model=TenantCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> TenantCreateResponse:
    repo = TenantRepository(session)
    tenant = await repo.create_tenant(body.name)

    # Generate the key, show it ONCE, store only its hash.
    plaintext = generate_api_key()
    await repo.add_api_key(
        tenant_id=tenant.id,
        key_hash=hash_api_key(plaintext),
        key_prefix=key_prefix(plaintext),
        name="default",
    )
    await session.commit()
    return TenantCreateResponse(
        tenant_id=str(tenant.id), api_key=plaintext, key_prefix=key_prefix(plaintext)
    )
