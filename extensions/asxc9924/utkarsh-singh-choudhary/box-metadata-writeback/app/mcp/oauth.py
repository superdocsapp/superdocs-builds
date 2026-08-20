"""Minimal OAuth 2.0 authorization-code flow protecting the MCP tool
surface.

The task doc explicitly flags this as something SuperDocs has not built
themselves and candidates MAY build against: "a full OAuth authorization
flow on the MCP surface." This is that -- a real (if deliberately small)
implementation: an authorization endpoint that issues a short-lived code,
a token endpoint that exchanges it for a bearer access token, and a
verification function the MCP server calls before running any tool.

Not a production-grade auth server (no PKCE, no persistent storage, a
single hardcoded client) -- it's scoped to demonstrate the actual
mechanics (code issuance, code-for-token exchange, token expiry, and
enforcement at the tool boundary) rather than to be a real identity
provider. That scope is a deliberate choice, not an oversight: see the
README's "what I cut" section.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Optional

CODE_TTL_SECONDS = 60
TOKEN_TTL_SECONDS = 3600

# A single demo client, standing in for "the coding agent that registered
# itself" the task doc describes elsewhere for the SuperDocs API itself.
_REGISTERED_CLIENTS = {"demo-agent-client": "demo-agent-secret"}


@dataclass
class AuthCode:
    code: str
    client_id: str
    issued_at: float


@dataclass
class AccessToken:
    token: str
    client_id: str
    issued_at: float


class OAuthServer:
    def __init__(self) -> None:
        self._codes: dict[str, AuthCode] = {}
        self._tokens: dict[str, AccessToken] = {}

    def authorize(self, client_id: str) -> str:
        """Step 1: issue a short-lived authorization code for a known
        client. A real flow would redirect a logged-in user through a
        consent screen first; that's out of scope here (see README)."""
        if client_id not in _REGISTERED_CLIENTS:
            raise PermissionError(f"unknown client_id {client_id}")
        code = secrets.token_urlsafe(24)
        self._codes[code] = AuthCode(code=code, client_id=client_id, issued_at=time.time())
        return code

    def exchange_code_for_token(self, code: str, client_id: str, client_secret: str) -> str:
        """Step 2: trade a valid, unexpired code for a bearer token."""
        if _REGISTERED_CLIENTS.get(client_id) != client_secret:
            raise PermissionError("invalid client credentials")
        entry = self._codes.pop(code, None)
        if entry is None:
            raise PermissionError("unknown or already-used authorization code")
        if entry.client_id != client_id:
            raise PermissionError("code was not issued to this client")
        if time.time() - entry.issued_at > CODE_TTL_SECONDS:
            raise PermissionError("authorization code expired")
        token = secrets.token_urlsafe(32)
        self._tokens[token] = AccessToken(token=token, client_id=client_id, issued_at=time.time())
        return token

    def verify(self, token: Optional[str]) -> bool:
        """Called at the MCP tool boundary before process_box_file runs."""
        if not token:
            return False
        entry = self._tokens.get(token)
        if entry is None:
            return False
        if time.time() - entry.issued_at > TOKEN_TTL_SECONDS:
            del self._tokens[token]
            return False
        return True
