"""Errors that name the cause AND the fix.

Every exception in this package answers two questions in its message:
what went wrong, and what the caller should do about it. A bare
``KeyError: 'usage'`` three frames deep costs a reader ten minutes;
``BudgetExceeded: ... fix: raise --max-ops or run --weeks 12`` costs zero.
"""

from __future__ import annotations


class SuperDocsError(Exception):
    """Base class. Carries a cause and a suggested fix."""

    def __init__(self, cause: str, fix: str = "") -> None:
        self.cause = cause
        self.fix = fix
        msg = cause if not fix else f"{cause}\n  fix: {fix}"
        super().__init__(msg)


class AuthError(SuperDocsError):
    pass


class QuotaExhausted(SuperDocsError):
    """The SuperDocs account itself is out of billable operations."""


class BudgetExceeded(SuperDocsError):
    """OUR self-imposed spending cap would be crossed. Raised BEFORE the call."""


class ApiError(SuperDocsError):
    def __init__(self, status: int, path: str, body: str) -> None:
        self.status = status
        self.path = path
        self.body = body[:800]
        fix = {
            400: "Check the request body against https://api.superdocs.app/openapi.json.",
            401: "SUPERDOCS_API_KEY is missing, malformed or revoked. Re-check .env.",
            403: "The key is valid but not allowed here. Check the account tier.",
            404: "Wrong path or the session/document id does not exist on this account.",
            413: "Body too large for the gateway (~32MB). Use the pre-signed upload flow.",
            422: "A field failed validation. The body below names the field.",
            429: "Rate limited. The client already retries with backoff; slow the caller down.",
            504: "Gateway timeout. Retry the same work on POST /v1/chat/async instead.",
        }.get(status, "Retry once; if it persists, capture the body and report it as a bug.")
        super().__init__(f"HTTP {status} from {path}: {self.body}", fix)


class TransportError(SuperDocsError):
    pass


class ReplayMiss(SuperDocsError):
    """A test asked for a request that is not in the recorded cassette."""
