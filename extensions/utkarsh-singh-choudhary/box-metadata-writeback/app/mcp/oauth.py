"""OAuth 2.0 authorization-code flow (with PKCE) protecting the MCP tool
surface.

The task doc explicitly flags this as something SuperDocs has not built
themselves and candidates MAY build against: "a full OAuth authorization
flow on the MCP surface." This is that -- a real (if deliberately small)
implementation: an authorization endpoint that issues a short-lived code,
a token endpoint that exchanges it for a bearer access token (+ refresh
token), and a verification function the MCP server calls before running
any tool.

Round-3 additions over the original minimal version:
  - PKCE (RFC 7636, S256): the client sends a code_challenge at
    authorize() time and the matching code_verifier at exchange time.
    Without this, a code intercepted between authorize and exchange
    (e.g. leaked via a referrer header or a malicious redirect target)
    is directly usable by whoever intercepted it; PKCE means the
    interceptor also needs the verifier, which never travels over the
    same channel as the code.
  - state parameter: caller-supplied opaque value round-tripped through
    authorize() -> returned alongside the code, letting the caller
    detect a code that wasn't the response to *their* request (CSRF on
    the authorization step).
  - refresh tokens: exchange_code_for_token() now also mints a refresh
    token; refresh() trades it for a new access token without
    re-running the authorization step, and rotates the refresh token
    itself (single-use) so a leaked refresh token has a bounded window
    rather than being a permanent bearer credential.

Still not a production-grade auth server: no persistent storage (in
Redis/DB terms) and still one hardcoded demo client rather than dynamic
client registration -- that scope is a deliberate choice, not an
oversight; see the README's "what I cut" section. PKCE and refresh
rotation are protocol correctness, not deployment infrastructure, so
they're in scope for "make it more advanced" even without a real
persistent store.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Optional

CODE_TTL_SECONDS = 60
TOKEN_TTL_SECONDS = 3600
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# A single demo client, standing in for "the coding agent that registered
# itself" the task doc describes elsewhere for the SuperDocs API itself.
_REGISTERED_CLIENTS = {"demo-agent-client": "demo-agent-secret"}


def _b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def compute_code_challenge(code_verifier: str) -> str:
    """S256 transform per RFC 7636 -- the value a client sends at
    authorize() time, derived from a verifier only it holds."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return _b64url_no_pad(digest)


@dataclass
class AuthCode:
    code: str
    client_id: str
    issued_at: float
    state: Optional[str] = None
    code_challenge: Optional[str] = None


@dataclass
class AccessToken:
    token: str
    client_id: str
    issued_at: float


@dataclass
class RefreshToken:
    token: str
    client_id: str
    issued_at: float
    used: bool = False


class OAuthServer:
    def __init__(self) -> None:
        self._codes: dict[str, AuthCode] = {}
        self._tokens: dict[str, AccessToken] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._last_refresh_token: Optional[str] = None
        self._last_state: Optional[str] = None

    def authorize(
        self,
        client_id: str,
        state: Optional[str] = None,
        code_challenge: Optional[str] = None,
    ) -> str:
        """Step 1: issue a short-lived authorization code for a known
        client. `state` and `code_challenge` are optional so existing
        callers (server.py's internal demo flow) keep working
        unchanged; a real external client should always supply both.
        A real flow would also redirect a logged-in user through a
        consent screen first; that's out of scope here (see README)."""
        if client_id not in _REGISTERED_CLIENTS:
            raise PermissionError(f"unknown client_id {client_id}")
        code = secrets.token_urlsafe(24)
        self._codes[code] = AuthCode(
            code=code,
            client_id=client_id,
            issued_at=time.time(),
            state=state,
            code_challenge=code_challenge,
        )
        return code

    def exchange_code_for_token(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        code_verifier: Optional[str] = None,
    ) -> str:
        """Step 2: trade a valid, unexpired code for a bearer token
        (and, as a side effect, mints a refresh token retrievable via
        last_refresh_token() -- kept as a separate accessor rather than
        changing this method's return type, so every existing call site
        that does `token = exchange_code_for_token(...)` keeps working
        unchanged).

        If the code was issued with a code_challenge (PKCE), the caller
        MUST supply the matching code_verifier here, checked with a
        constant-time comparison against the S256 transform -- a code
        issued with a challenge can never be exchanged with the wrong
        verifier, or with no verifier at all."""
        if _REGISTERED_CLIENTS.get(client_id) != client_secret:
            raise PermissionError("invalid client credentials")
        entry = self._codes.pop(code, None)
        if entry is None:
            raise PermissionError("unknown or already-used authorization code")
        if entry.client_id != client_id:
            raise PermissionError("code was not issued to this client")
        if time.time() - entry.issued_at > CODE_TTL_SECONDS:
            raise PermissionError("authorization code expired")
        if entry.code_challenge is not None:
            if code_verifier is None:
                raise PermissionError("PKCE code_verifier required for this code")
            expected = compute_code_challenge(code_verifier)
            if not secrets.compare_digest(expected, entry.code_challenge):
                raise PermissionError("PKCE code_verifier does not match code_challenge")

        token = secrets.token_urlsafe(32)
        self._tokens[token] = AccessToken(token=token, client_id=client_id, issued_at=time.time())

        refresh = secrets.token_urlsafe(32)
        self._refresh_tokens[refresh] = RefreshToken(token=refresh, client_id=client_id, issued_at=time.time())
        self._last_refresh_token = refresh
        self._last_state = entry.state
        return token

    def last_refresh_token(self) -> Optional[str]:
        """The refresh token minted by the most recent
        exchange_code_for_token() (or refresh()) call."""
        return self._last_refresh_token

    def last_state(self) -> Optional[str]:
        """The `state` value that was round-tripped through the most
        recent exchange -- callers compare this against what they sent
        to authorize() to detect a cross-request code (CSRF)."""
        return self._last_state

    def refresh(self, refresh_token: str, client_id: str, client_secret: str) -> str:
        """Trades a still-valid, not-yet-used refresh token for a new
        access token, without re-running the authorization step. The
        refresh token itself is single-use: it's marked used and a new
        one is minted (retrievable via last_refresh_token()), so a
        leaked refresh token is only ever good for one silent renewal
        before the legitimate client's next refresh invalidates it --
        rotation, not a permanent bearer credential."""
        if _REGISTERED_CLIENTS.get(client_id) != client_secret:
            raise PermissionError("invalid client credentials")
        entry = self._refresh_tokens.get(refresh_token)
        if entry is None:
            raise PermissionError("unknown refresh token")
        if entry.client_id != client_id:
            raise PermissionError("refresh token was not issued to this client")
        if entry.used:
            # Reuse of an already-rotated refresh token is a strong
            # signal of token theft -- revoke every token for this
            # client rather than silently failing, matching how a real
            # authorization server (e.g. Box's own) treats refresh
            # token reuse.
            self._revoke_all_for_client(client_id)
            raise PermissionError("refresh token already used; all tokens for this client revoked")
        if time.time() - entry.issued_at > REFRESH_TOKEN_TTL_SECONDS:
            raise PermissionError("refresh token expired")

        entry.used = True
        new_access = secrets.token_urlsafe(32)
        self._tokens[new_access] = AccessToken(token=new_access, client_id=client_id, issued_at=time.time())
        new_refresh = secrets.token_urlsafe(32)
        self._refresh_tokens[new_refresh] = RefreshToken(token=new_refresh, client_id=client_id, issued_at=time.time())
        self._last_refresh_token = new_refresh
        return new_access

    def _revoke_all_for_client(self, client_id: str) -> None:
        for tok, entry in list(self._tokens.items()):
            if entry.client_id == client_id:
                del self._tokens[tok]
        for tok, entry in list(self._refresh_tokens.items()):
            if entry.client_id == client_id:
                del self._refresh_tokens[tok]

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
