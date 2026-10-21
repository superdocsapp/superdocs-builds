"""Typed SuperDocs errors. Messages never include API keys or auth headers."""

from __future__ import annotations


class SuperDocsError(Exception):
    """Base error for the SuperDocs adapter."""

    def __init__(self, message: str, *, status_code: int | None = None, cause: str | None = None):
        self.status_code = status_code
        self.cause = cause
        super().__init__(message)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self)!r}, status_code={self.status_code})"


class ConfigurationError(SuperDocsError):
    """Missing or invalid local configuration (for example no API key)."""


class AuthenticationError(SuperDocsError):
    """HTTP 401 or 403."""


class RateLimitError(SuperDocsError):
    """HTTP 429. retry_after_seconds is taken from Retry-After when present."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        status_code: int | None = 429,
        cause: str | None = None,
    ):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message, status_code=status_code, cause=cause)


class TransientHttpError(SuperDocsError):
    """5xx or similar, only retried on clearly safe GET operations."""


class MalformedResponseError(SuperDocsError):
    """Response body was not the expected JSON/shape."""


class ProposedChangeParseError(SuperDocsError):
    """Proposed-change payload could not be parsed into reviewable items."""


class JobFailedError(SuperDocsError):
    """Async job reached status=failed."""


class JobTimeoutError(SuperDocsError):
    """Polling exceeded the configured wait. The job may still be running."""


class AmbiguousOutcomeError(SuperDocsError):
    """A state-changing request did not yield a known result. Do not blind-retry."""

    def __init__(self, message: str, *, operation_key: str | None = None, cause: str | None = None):
        self.operation_key = operation_key
        super().__init__(message, cause=cause)


class ApprovalError(SuperDocsError):
    """Approve/reject request failed."""


class ExportError(SuperDocsError):
    """Export did not produce downloadable bytes."""
