"""Framework-neutral input and output models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class JobStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExportFormat(str, Enum):
    DOCX = "docx"
    PDF = "pdf"
    HTML = "html"
    MARKDOWN = "markdown"
    TXT = "txt"


@dataclass(frozen=True)
class UploadResult:
    session_id: str
    document_id: str | None = None
    title: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ProposedChange:
    change_id: str
    chunk_id: str | None = None
    content: Any = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Job:
    job_id: str
    session_id: str
    status: JobStatus
    progress: int = 0
    proposed_changes: tuple[ProposedChange, ...] = ()
    result: Mapping[str, Any] | None = None
    error: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ExportedDocument:
    content: bytes
    format: ExportFormat
    filename: str
    content_type: str | None = None

    def save(self, destination: str | Path) -> Path:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.content)
        return path


@dataclass(frozen=True)
class EditResult:
    session_id: str
    document_id: str | None
    job_id: str
    approved_change_ids: tuple[str, ...]
    export: ExportedDocument
    final_result: Mapping[str, Any] | None = None

    def canonical(self) -> dict[str, Any]:
        """Stable result shape used by every framework binding."""
        return {
            "status": "completed",
            "approved_changes": len(self.approved_change_ids),
            "export_format": self.export.format.value,
            "filename": self.export.filename,
            "size_bytes": len(self.export.content),
        }
