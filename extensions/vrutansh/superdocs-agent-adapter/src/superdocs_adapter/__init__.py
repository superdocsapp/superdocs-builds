"""Public package surface for the SuperDocs agent adapter."""

from .adapter import SuperDocsAdapter
from .client import SuperDocsClient
from .errors import (
    ConfigurationError,
    InvalidResponseError,
    JobFailedError,
    JobTimeoutError,
    SuperDocsAPIError,
    SuperDocsError,
)
from .models import (
    EditResult,
    ExportFormat,
    Job,
    JobStatus,
    ProposedChange,
    UploadResult,
)
from .tools import SuperDocsToolset, ToolSpec

__all__ = [
    "ConfigurationError",
    "EditResult",
    "ExportFormat",
    "InvalidResponseError",
    "Job",
    "JobFailedError",
    "JobStatus",
    "JobTimeoutError",
    "ProposedChange",
    "SuperDocsAPIError",
    "SuperDocsAdapter",
    "SuperDocsClient",
    "SuperDocsError",
    "SuperDocsToolset",
    "ToolSpec",
    "UploadResult",
]

__version__ = "0.1.0"
