"""The SuperDocs seam: a typed client protocol, the real API models, and a deterministic fake.

The fake is a *real* implementation of the same contract — it assigns chunk ids on upload,
proposes edits, and (critically) returns proposed changes the way the live API does: as a
JSON-encoded string inside job metadata, so the double-parse that trips up most integrators
is exercised by the offline test suite and can never silently regress.
"""

from notion_review.superdocs.base import SuperDocsClient, parse_pending_changes
from notion_review.superdocs.fake import FakeSuperDocsClient
from notion_review.superdocs.models import (
    ApprovalDecision,
    ApproveResult,
    ChunkDiff,
    ExportResult,
    Job,
    JobStatus,
    UploadResult,
    Usage,
)

__all__ = [
    "ApprovalDecision",
    "ApproveResult",
    "ChunkDiff",
    "ExportResult",
    "FakeSuperDocsClient",
    "Job",
    "JobStatus",
    "SuperDocsClient",
    "UploadResult",
    "Usage",
    "parse_pending_changes",
]
