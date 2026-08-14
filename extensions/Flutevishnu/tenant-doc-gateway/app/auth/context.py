"""The authenticated caller's identity, resolved once per request.

Every tenant-scoped repository REQUIRES a TenantContext, so it is impossible to
run a tenant query without stating whose data you are allowed to touch.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    api_key_id: uuid.UUID
