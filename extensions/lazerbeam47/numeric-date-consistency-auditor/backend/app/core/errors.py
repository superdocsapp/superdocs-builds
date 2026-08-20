"""Typed error hierarchy.

Errors carry a `retryable` flag so the workflow engine can decide between
retrying a node and failing the run — the decision lives with the error, not
scattered across call sites.
"""

from __future__ import annotations


class SuperDocsError(Exception):
    """Base class for every application error."""

    status_code: int = 500
    retryable: bool = False
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "details": self.details}


class ValidationError(SuperDocsError):
    status_code = 422
    code = "validation_error"


class UnsupportedFileType(ValidationError):
    code = "unsupported_file_type"


class FileTooLarge(ValidationError):
    code = "file_too_large"


class NotFoundError(SuperDocsError):
    status_code = 404
    code = "not_found"


class ConflictError(SuperDocsError):
    status_code = 409
    code = "conflict"


class ParsingError(SuperDocsError):
    code = "parsing_error"
    retryable = False


class LLMError(SuperDocsError):
    code = "llm_error"
    retryable = True


class LLMUnavailable(LLMError):
    """No key / offline mode. Callers must degrade gracefully, not crash."""

    code = "llm_unavailable"
    retryable = False


class PromptInjectionDetected(SuperDocsError):
    status_code = 400
    code = "prompt_injection_detected"
