from __future__ import annotations

from typing import Any


class SuperDocsError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
        retryable: bool = False,
        suggested_action: str | None = None,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.retryable = retryable
        self.suggested_action = suggested_action
        self.details = details

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, code={self.code!r}, "
            f"request_id={self.request_id!r}, retryable={self.retryable!r})"
        )


class AuthenticationError(SuperDocsError):
    pass


class RateLimitError(SuperDocsError):
    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ConflictError(SuperDocsError):
    pass


class ValidationError(SuperDocsError):
    pass


class ServerError(SuperDocsError):
    pass


class TransportError(SuperDocsError):
    pass


class SuperDocsTimeoutError(TransportError):
    pass


def _retry_after(headers: dict[str, str]) -> float | None:
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except ValueError:
        return None


def error_from_response(status_code: int, headers: dict[str, str], payload: Any) -> SuperDocsError:
    code = None
    message = f"SuperDocs request failed with HTTP {status_code}"
    suggested: str | None = None
    if isinstance(payload, dict):
        code = str(payload.get("code") or payload.get("detail") or "api_error")
        message = str(payload.get("message") or payload.get("detail") or message)
        suggested = payload.get("suggested_action")

    retryable = status_code == 408 or status_code == 429 or 500 <= status_code <= 599
    if suggested is None:
        if status_code == 401 or status_code == 403:
            suggested = "Verify SUPERDOCS_API_KEY and its workspace permissions."
        elif status_code == 409:
            suggested = "Resolve the active job or document version conflict, then retry."
        elif retryable:
            suggested = "Retry with the same idempotency key."
        else:
            suggested = "Inspect the request payload and API documentation."

    kwargs: dict[str, Any] = {
        "status_code": status_code,
        "code": code,
        "request_id": headers.get("x-request-id") or headers.get("X-Request-Id"),
        "retryable": retryable,
        "suggested_action": suggested,
        "details": payload,
    }
    if status_code in {401, 403}:
        return AuthenticationError(message, **kwargs)
    if status_code == 429:
        return RateLimitError(message, retry_after=_retry_after(headers), **kwargs)
    if status_code == 409:
        return ConflictError(message, **kwargs)
    if status_code in {400, 404, 413, 415, 422}:
        return ValidationError(message, **kwargs)
    if status_code >= 500:
        return ServerError(message, **kwargs)
    return SuperDocsError(message, **kwargs)
