"""Seed a demo tenant + API key directly in the DB (local dev convenience).

Prints the plaintext key ONCE. Uses only synthetic data. Run:
    python -m scripts.seed_tenants "Acme Corp"
"""

from __future__ import annotations

import asyncio
import sys

from app.auth.hashing import generate_api_key, hash_api_key, key_prefix
from app.db.repositories import TenantRepository
from app.db.session import get_sessionmaker


async def main(name: str) -> None:
    sm = get_sessionmaker()
    async with sm() as session:
        repo = TenantRepository(session)
        tenant = await repo.create_tenant(name)
        plaintext = generate_api_key()
        await repo.add_api_key(
            tenant_id=tenant.id,
            key_hash=hash_api_key(plaintext),
            key_prefix=key_prefix(plaintext),
            name="seed",
        )
        await session.commit()
        print(f"tenant_id={tenant.id}")
        print(f"api_key={plaintext}   # shown once, store it now")


if __name__ == "__main__":
    tenant_name = sys.argv[1] if len(sys.argv) > 1 else "Demo Tenant"
    asyncio.run(main(tenant_name))
