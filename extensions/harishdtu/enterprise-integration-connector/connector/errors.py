"""
Typed error hierarchy. SuperDocs' API returns a uniform `{"detail": "..."}` shape
on every error (see docs.superdocs.app/errors/error-codes) with no structured
`error_code` field for most cases — retryability and handling must be inferred
from the HTTP status code, never from parsing the `detail` string (the docs
explicitly warn its wording may change).

Every exception carries the original status code and detail message so callers
(and platform error-handling UIs) can show something meaningful, but application
logic — retries, branching — must key off the exception *class*, never off
`str(exc)`.
"""
from __future__ import annotations


class SuperDocsConnectorError(Exception):
    """Base class for every typed error this connector raises."""

    #: Whether the connector's HTTP client should retry this class of error.
    #: Overridden per subclass; see http_client.py for how this is consumed.
    retryable: bool = False

    def __init__(self, message: str, *, status_code: int | None = None,
                 detail: str | None = None, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(status_code={self.status_code}, detail={self.detail!r})"


class AuthenticationError(SuperDocsConnectorError):
    """401 — missing/invalid/revoked API key. Not retryable: the key won't fix itself."""
    retryable = False


class ValidationError(SuperDocsConnectorError):
    """400 or 422 — malformed request. Not retryable without changing the payload."""
    retryable = False


class PermissionError(SuperDocsConnectorError):  # noqa: A001 - intentional shadow, scoped to this module
    """403 — resource not owned by this API key, or a wrong agent-takeover code."""
    retryable = False


class NotFoundError(SuperDocsConnectorError):
    """404 — job/session/template/attachment doesn't exist, or (commonly) a job
    older than SuperDocs' ~1 hour retention window."""
    retryable = False


class ConflictError(SuperDocsConnectorError):
    """409 — e.g. calling /approve on a continue_prompt pause, or vice versa;
    revert while a job is in flight. Not blindly retryable: the caller sent the
    wrong operation for the current state, not a transient failure."""
    retryable = False


class PayloadTooLargeError(SuperDocsConnectorError):
    """413 — request or export payload over the size cap. Surfaces as a
    payload-size/splitting problem, per the brief: retrying the identical
    request will fail identically. The caller should switch to the pre-signed
    upload/export flow or split the document."""
    retryable = False


class UnsupportedFormatError(SuperDocsConnectorError):
    """415 — file extension not supported (including legacy .doc uploads)."""
    retryable = False


class RateLimitError(SuperDocsConnectorError):
    """
    429 — two distinct flavors merged into one typed error, distinguished by
    `retry_after_seconds`:
      - Application 429 (quota/cooldown): JSON body, always carries Retry-After.
        `retry_after_seconds` is set from that header — honor it exactly.
      - Infrastructure 429 (traffic surge): plain text, no Retry-After.
        `retry_after_seconds` is None — the http client falls back to
        exponential backoff + jitter for this case.
    """
    retryable = True


class ServerError(SuperDocsConnectorError):
    """500 — unexpected server error. Retryable with backoff."""
    retryable = True


class TimeoutError(SuperDocsConnectorError):  # noqa: A001
    """504 — the AI processing exceeded SuperDocs' 30-minute wall-clock cap on a
    *synchronous* call. Retryable in principle, but the connector should prefer
    switching to the async job flow over blindly re-sending an identical
    synchronous request that is likely to time out again — see
    operations/edit_by_instruction.py."""
    retryable = True


class ExportWarning(SuperDocsConnectorError):
    """
    Not a failure. Exports can complete successfully with non-fatal issues
    reported via the X-Export-Warnings header (e.g. an image URL that 404'd).
    This class exists so ExportOutput can carry structured warnings without
    ever raising them as errors — see schemas/export.py. It subclasses
    SuperDocsConnectorError only for a consistent typed-error family; connector
    code must never `raise` this for a successful export.
    """
    retryable = False


class UnknownSuperDocsError(SuperDocsConnectorError):
    """Any status code not explicitly mapped above (defensive catch-all so a
    new/undocumented SuperDocs status code fails loud and typed, not as a raw
    httpx exception leaking into platform recipe logic)."""
    retryable = False


#: Status-code → exception class. Central, single source of truth for error
#: mapping; http_client.py is the only place this is consulted.
STATUS_CODE_MAP: dict[int, type[SuperDocsConnectorError]] = {
    400: ValidationError,
    401: AuthenticationError,
    403: PermissionError,
    404: NotFoundError,
    409: ConflictError,
    410: PermissionError,  # agent-takeover link permanently gone; not applicable to this connector's ops, mapped defensively
    413: PayloadTooLargeError,
    415: UnsupportedFormatError,
    422: ValidationError,
    429: RateLimitError,
    500: ServerError,
    504: TimeoutError,
}
