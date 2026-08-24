"""Typed errors from the SuperDocs upstream, so callers can degrade gracefully."""

from __future__ import annotations


class SuperDocsError(Exception):
    """Base class for all upstream failures."""


class SuperDocsAPIError(SuperDocsError):
    def __init__(self, status_code: int, message: str, payload: dict | None = None) -> None:
        super().__init__(f"SuperDocs API {status_code}: {message}")
        self.status_code = status_code
        self.message = message
        self.payload = payload or {}


class SuperDocsTimeoutError(SuperDocsError):
    """The upstream took too long — the caller should retry or poll later."""
