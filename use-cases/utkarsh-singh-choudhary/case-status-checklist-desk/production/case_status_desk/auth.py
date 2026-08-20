"""
Minimal API-key auth with roles. Every caller must send:
    Authorization: Bearer <key>

Keys are configured via the STAFF_API_KEYS env var as a comma-separated
list of "key:staff_name:role" triples, e.g.:
    STAFF_API_KEYS=sk_abc123:Priya:preparer,sk_def456:Marco:approver

Roles:
    preparer  -- can list/view cases and draft letters
    approver  -- can also approve and export letters
    admin     -- can do everything a preparer/approver can

For backward compatibility, a two-part "key:name" entry (no role) is
treated as admin, so existing single-tier deployments keep working.

This is intentionally simple -- swap for real SSO/OAuth (with roles
pulled from your identity provider) before this grows past a handful of
internal staff.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from fastapi import Header, HTTPException, status

APPROVER_ROLES = {"approver", "admin"}
PREPARER_ROLES = {"preparer", "approver", "admin"}


@dataclass
class StaffUser:
    name: str
    role: str

    def can_approve(self) -> bool:
        return self.role in APPROVER_ROLES


def _load_keys() -> dict[str, StaffUser]:
    raw = os.environ.get("STAFF_API_KEYS", "")
    keys: dict[str, StaffUser] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) == 2:
            key, name = parts
            role = "admin"  # backward-compatible default
        elif len(parts) == 3:
            key, name, role = parts
        else:
            continue
        role = role.strip().lower()
        if role not in PREPARER_ROLES:
            continue
        keys[key.strip()] = StaffUser(name=name.strip(), role=role)
    return keys


def _authenticate(authorization: str) -> StaffUser:
    keys = _load_keys()
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: STAFF_API_KEYS not set",
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    user = keys.get(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return user


def require_staff_user(authorization: str = Header(default="")) -> StaffUser:
    """FastAPI dependency: any authenticated staff member (preparer or
    higher). Used for read endpoints and drafting.

    Dispatches to SSO (sso.py) if OIDC_ISSUER/OIDC_AUDIENCE are set,
    otherwise falls back to the STAFF_API_KEYS allowlist below. This lets
    a deployment turn on real SSO without changing every call site.
    """
    from . import sso
    if sso.SSO_ENABLED:
        return sso.require_sso_user(authorization)
    return _authenticate(authorization)


def require_approver(authorization: str = Header(default="")) -> StaffUser:
    """FastAPI dependency: only approver/admin roles. Used for the
    approve and export endpoints, so a preparer cannot self-approve
    their own draft."""
    user = require_staff_user(authorization)
    if not user.can_approve():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role {user.role!r} cannot approve or export letters (requires approver or admin).",
        )
    return user

