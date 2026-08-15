"""
Enterprise Integration-Platform Connector for SuperDocs.

Models SuperDocs document operations (generate-from-template, edit-by-instruction,
submit-for-approval, poll-for-completion, export) as typed, platform-agnostic
operations suitable for wiring into Workato, Tray, Boomi, MuleSoft, or any other
enterprise integration platform's connector SDK.

This package is REST-first (see docs.superdocs.app) and deliberately does not
depend on the SuperDocs MCP server or on this repository's Task 1 system.
"""
from connector.callbacks import (
    BoomiCallbackDispatcher,
    CallbackDeliveryError,
    CallbackDispatcher,
    JobCallbackEvent,
    LoggingCallbackDispatcher,
    MuleSoftCallbackDispatcher,
    TrayCallbackDispatcher,
    WebhookCallbackDispatcher,
    WorkatoCallbackDispatcher,
)
from connector.config import ConnectorConfig
from connector.errors import (
    AuthenticationError,
    ConflictError,
    ExportWarning,
    NotFoundError,
    PayloadTooLargeError,
    PermissionError,
    RateLimitError,
    ServerError,
    SuperDocsConnectorError,
    TimeoutError,
    UnknownSuperDocsError,
    UnsupportedFormatError,
    ValidationError,
)
from connector.http_client import SuperDocsHTTPClient
from connector.worker import JobWorker

__all__ = [
    "ConnectorConfig",
    "SuperDocsHTTPClient",
    "JobWorker",
    "CallbackDispatcher",
    "CallbackDeliveryError",
    "JobCallbackEvent",
    "LoggingCallbackDispatcher",
    "WebhookCallbackDispatcher",
    "WorkatoCallbackDispatcher",
    "TrayCallbackDispatcher",
    "BoomiCallbackDispatcher",
    "MuleSoftCallbackDispatcher",
    "SuperDocsConnectorError",
    "AuthenticationError",
    "ValidationError",
    "PermissionError",
    "NotFoundError",
    "ConflictError",
    "PayloadTooLargeError",
    "UnsupportedFormatError",
    "RateLimitError",
    "ServerError",
    "TimeoutError",
    "ExportWarning",
    "UnknownSuperDocsError",
]
