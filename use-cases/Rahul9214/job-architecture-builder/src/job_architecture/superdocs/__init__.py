"""SuperDocs REST adapter. Domain reasoning does not import this package's HTTP client."""

from job_architecture.superdocs.client import SuperDocsClient
from job_architecture.superdocs.config import load_settings
from job_architecture.superdocs.errors import (
    AmbiguousOutcomeError,
    ApprovalError,
    AuthenticationError,
    ConfigurationError,
    ExportError,
    JobFailedError,
    JobTimeoutError,
    MalformedResponseError,
    ProposedChangeParseError,
    RateLimitError,
    SuperDocsError,
)
from job_architecture.superdocs.models import (
    ApprovalResult,
    AsyncJobHandle,
    DocumentRef,
    ExportResult,
    JobSnapshot,
    ReviewDecision,
    SavedDocument,
    SearchAccepted,
    SessionRoster,
    SuperDocsSettings,
    TemplateRef,
    UploadResult,
)
from job_architecture.superdocs.parsing import parse_pending_changes
from job_architecture.superdocs.protocol import SuperDocsClientProtocol

__all__ = [
    "AmbiguousOutcomeError",
    "ApprovalError",
    "ApprovalResult",
    "AsyncJobHandle",
    "AuthenticationError",
    "ConfigurationError",
    "DocumentRef",
    "ExportError",
    "ExportResult",
    "JobFailedError",
    "JobSnapshot",
    "JobTimeoutError",
    "MalformedResponseError",
    "ProposedChangeParseError",
    "RateLimitError",
    "ReviewDecision",
    "SavedDocument",
    "SearchAccepted",
    "SessionRoster",
    "SuperDocsClient",
    "SuperDocsClientProtocol",
    "SuperDocsError",
    "SuperDocsSettings",
    "TemplateRef",
    "UploadResult",
    "load_settings",
    "parse_pending_changes",
]
