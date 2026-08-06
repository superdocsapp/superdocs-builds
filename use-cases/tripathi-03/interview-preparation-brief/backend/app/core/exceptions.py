"""Domain and HTTP exceptions."""

from fastapi import HTTPException, status


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class DocumentParseError(AppError):
    """Raised when a resume/JD file cannot be parsed."""


class UnsupportedFileTypeError(AppError):
    """Raised for unsupported upload extensions."""


class EvidenceNotFoundError(AppError):
    """Raised when resume retrieval yields no usable evidence."""


class BriefNotFoundError(AppError):
    """Raised when a brief id does not exist."""


class SessionNotFoundError(AppError):
    """Raised when an ingest session does not exist."""


class LLMConfigurationError(AppError):
    """Raised when LLM/embedding credentials are missing or invalid."""


def http_not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def http_bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def http_unprocessable(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )
