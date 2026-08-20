"""
SSO auth via OpenID Connect (OIDC), as an alternative to the shared
API-key allowlist in auth.py.

This works generically against any standard OIDC provider -- Okta, Azure
AD / Entra ID, Google Workspace, Auth0, etc. -- because they all issue
the same kind of signed JWT access/ID tokens and expose the same
discovery document shape. What's NOT generic, and what you must supply,
is:

  1. OIDC_ISSUER        -- e.g. "https://your-org.okta.com/oauth2/default"
                            or "https://login.microsoftonline.com/<tenant>/v2.0"
  2. OIDC_AUDIENCE       -- the client/API identifier your provider issues
                            tokens for
  3. A role claim mapping -- see ROLE_CLAIM below. Every provider puts
     roles/groups in a different claim (Okta: often a custom
     "groups" claim; Azure AD: "roles"; Auth0: a namespaced custom
     claim like "https://yourapp.com/roles"). You MUST set OIDC_ROLE_CLAIM
     to match your provider's actual claim name and make sure your IdP
     is configured to emit `preparer`/`approver`/`admin` values into it
     (or set OIDC_ROLE_MAP to translate your IdP's real group names into
     those three roles).

Until those are configured, this module is inert and app.py continues
using the STAFF_API_KEYS path in auth.py. Set OIDC_ISSUER to switch on.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from functools import lru_cache

import requests
from fastapi import Header, HTTPException, status

try:
    from jose import jwt
    from jose.exceptions import JWTError
    _HAS_JOSE = True
except ImportError:
    _HAS_JOSE = False

from .auth import StaffUser, PREPARER_ROLES, APPROVER_ROLES

OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "")
OIDC_AUDIENCE = os.environ.get("OIDC_AUDIENCE", "")
OIDC_ROLE_CLAIM = os.environ.get("OIDC_ROLE_CLAIM", "roles")
# Optional: "IdpGroupName:role,OtherGroup:role" to translate real IdP
# group/role names into this app's preparer/approver/admin vocabulary.
OIDC_ROLE_MAP = dict(
    pair.split(":", 1) for pair in os.environ.get("OIDC_ROLE_MAP", "").split(",") if ":" in pair
)

SSO_ENABLED = bool(OIDC_ISSUER and OIDC_AUDIENCE)


@lru_cache(maxsize=1)
def _jwks_cache_key() -> str:
    # cache-buster placeholder; real TTL handled in _get_jwks below
    return OIDC_ISSUER


_jwks_state: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_S = 3600


def _get_jwks() -> dict:
    now = time.time()
    if _jwks_state["keys"] is not None and (now - _jwks_state["fetched_at"]) < _JWKS_TTL_S:
        return _jwks_state["keys"]
    discovery = requests.get(f"{OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration", timeout=10)
    discovery.raise_for_status()
    jwks_uri = discovery.json()["jwks_uri"]
    jwks_resp = requests.get(jwks_uri, timeout=10)
    jwks_resp.raise_for_status()
    _jwks_state["keys"] = jwks_resp.json()
    _jwks_state["fetched_at"] = now
    return _jwks_state["keys"]


def _map_role(raw_roles: list[str]) -> str:
    """Pick the highest-privilege role present, after applying
    OIDC_ROLE_MAP translation. Defaults to 'preparer' (least privilege)
    if nothing recognizable is found -- fail closed, not open."""
    mapped = {OIDC_ROLE_MAP.get(r, r) for r in raw_roles}
    if mapped & {"admin"}:
        return "admin"
    if mapped & APPROVER_ROLES:
        return "approver"
    if mapped & PREPARER_ROLES:
        return "preparer"
    return "preparer"


def require_sso_user(authorization: str = Header(default="")) -> StaffUser:
    """FastAPI dependency: validates a real OIDC bearer token (signature,
    issuer, audience, expiry) and maps its role claim into a StaffUser.

    Only usable once OIDC_ISSUER/OIDC_AUDIENCE are configured; raises a
    clear 500 otherwise so misconfiguration fails loudly rather than
    silently falling through to "no auth".
    """
    if not SSO_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SSO not configured (OIDC_ISSUER/OIDC_AUDIENCE unset). "
                   "Use the STAFF_API_KEYS path in auth.py instead, or configure SSO.",
        )
    if not _HAS_JOSE:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="python-jose not installed; add it to requirements.txt to enable SSO.",
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        jwks = _get_jwks()
        claims = jwt.decode(
            token, jwks, audience=OIDC_AUDIENCE, issuer=OIDC_ISSUER,
            options={"verify_at_hash": False},
        )
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")
    except requests.RequestException as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                             detail=f"Could not reach identity provider: {e}")

    name = claims.get("name") or claims.get("email") or claims.get("sub", "unknown")
    raw_roles = claims.get(OIDC_ROLE_CLAIM, [])
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    role = _map_role(raw_roles)
    return StaffUser(name=name, role=role)
