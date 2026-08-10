"""Adapter-specific exceptions with safe, actionable messages."""


class SuperDocsError(Exception):
    """Base exception for adapter failures."""


class ConfigurationError(SuperDocsError):
    """Raised when required adapter configuration is missing or invalid."""


class SuperDocsAPIError(SuperDocsError):
    """Raised when the SuperDocs API returns an unsuccessful response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"SuperDocs API returned HTTP {status_code}: {message}")


class InvalidResponseError(SuperDocsError):
    """Raised when a successful API response has an invalid shape."""


class JobFailedError(SuperDocsError):
    """Raised when an asynchronous SuperDocs job fails or is cancelled."""


class JobTimeoutError(SuperDocsError):
    """Raised when a job does not reach the required state before timeout."""
