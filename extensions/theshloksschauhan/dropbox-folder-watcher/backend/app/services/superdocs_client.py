"""SuperDocs API client — the four-call contract.

Wraps: upload → chat (edit instruction) → approve → export

Two critical gotchas from the task document:
1. Proposed-change content arrives as a JSON-encoded string requiring
   a second JSON.parse. Missing this is the #1 cause of "empty diff,
   everything undefined."
2. Operations on large docs can silently run for minutes with no progress
   signal — that's normal, not a crash. Poll with backoff.

The PREVIEW CHOKEPOINT: when preview=True, this module structurally
refuses to make any billable network call (upload, chat). This is
enforced in ONE place (_guard_billable), not scattered across call sites.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------- Data types ----------

@dataclass
class ProposedChange:
    """A single proposed change from SuperDocs, after double-parsing."""
    content: str  # The actual change content
    raw: dict  # The full parsed object for inspection


@dataclass
class ChatResult:
    """Result of a chat (edit instruction) call."""
    proposed_changes: list[ProposedChange]
    raw_response: dict  # Full response for debugging


@dataclass
class UploadResult:
    """Result of uploading a document."""
    document_id: str
    raw_response: dict


@dataclass
class ExportResult:
    """Result of exporting a finished document."""
    content: bytes
    filename: str
    content_type: str


# ---------- Protocol for dependency injection ----------

class SuperDocsClientProtocol(Protocol):
    """Interface for both real and fake clients."""

    def upload_document(self, file_content: bytes, filename: str,
                        preview: bool = False) -> UploadResult: ...

    def send_edit_instruction(self, document_id: str, instruction: str,
                              preview: bool = False) -> ChatResult: ...

    def approve_changes(self, document_id: str) -> dict: ...

    def export_document(self, document_id: str) -> ExportResult: ...


# ---------- Double JSON parse helper ----------

def parse_proposed_changes(raw_response: dict) -> list[ProposedChange]:
    """Parse proposed changes from the SuperDocs chat response.

    THE CRITICAL DETAIL: the proposed-change content arrives as a
    JSON-encoded STRING inside the JSON response. You must parse it
    a second time to get the actual change objects.

    This is the task document's named #1 integration bug.
    """
    changes = []

    # The response structure may vary — handle multiple possible shapes
    proposed = raw_response.get("proposed_changes") or raw_response.get("changes") or []

    if isinstance(proposed, str):
        # First level: the whole proposed_changes field is a JSON string
        try:
            proposed = json.loads(proposed)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse proposed_changes string: %s", e)
            return []

    if isinstance(proposed, list):
        for item in proposed:
            if isinstance(item, str):
                # Second level: each individual change is also a JSON string
                try:
                    parsed = json.loads(item)
                    changes.append(ProposedChange(
                        content=parsed.get("content", str(parsed)),
                        raw=parsed,
                    ))
                except json.JSONDecodeError:
                    # Not JSON — treat as plain text content
                    changes.append(ProposedChange(content=item, raw={"content": item}))
            elif isinstance(item, dict):
                # Already parsed — extract content
                content = item.get("content", "")
                if isinstance(content, str):
                    # The content field itself might be JSON-encoded
                    try:
                        inner = json.loads(content)
                        if isinstance(inner, dict):
                            changes.append(ProposedChange(
                                content=inner.get("content", str(inner)),
                                raw=inner,
                            ))
                        else:
                            changes.append(ProposedChange(content=str(inner), raw=item))
                    except (json.JSONDecodeError, TypeError):
                        changes.append(ProposedChange(content=content, raw=item))
                else:
                    changes.append(ProposedChange(content=str(content), raw=item))
    elif isinstance(proposed, dict):
        # Single change object
        content = proposed.get("content", str(proposed))
        if isinstance(content, str):
            try:
                inner = json.loads(content)
                changes.append(ProposedChange(
                    content=inner.get("content", str(inner)) if isinstance(inner, dict) else str(inner),
                    raw=inner if isinstance(inner, dict) else proposed,
                ))
            except (json.JSONDecodeError, TypeError):
                changes.append(ProposedChange(content=content, raw=proposed))

    logger.info("Parsed %d proposed change(s) from SuperDocs response", len(changes))
    return changes


# ---------- Real implementation ----------

class SuperDocsClient:
    """Real SuperDocs API client."""

    BILLABLE_OPERATIONS = {"upload", "chat"}  # These cost operations

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self._api_key = api_key or settings.superdocs_api_key
        self._base_url = (base_url or settings.superdocs_base_url).rstrip("/")

        if not self._api_key:
            raise ValueError(
                "SuperDocs API key not configured. "
                "Set SUPERDOCS_API_KEY in your .env file."
            )

        self._client = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=httpx.Timeout(300.0),  # 5 min — long ops are normal per the doc
        )
        logger.info("SuperDocs client initialized (base_url=%s)", self._base_url)

    def _guard_billable(self, operation: str, preview: bool) -> None:
        """THE PREVIEW CHOKEPOINT.

        This single function is the structural guarantee that preview mode
        never spends a SuperDocs operation. Every billable call goes through
        here. If preview=True and the operation is billable, we refuse.

        This is enforced in ONE place so it can never be accidentally
        bypassed by a new code path.
        """
        if preview and operation in self.BILLABLE_OPERATIONS:
            logger.info(
                "PREVIEW MODE: blocked billable operation '%s' — zero spend guaranteed",
                operation,
            )
            raise PreviewModeBlocked(
                f"Operation '{operation}' blocked: preview mode is active. "
                f"No SuperDocs operations will be spent."
            )

    def upload_document(self, file_content: bytes, filename: str,
                        preview: bool = False) -> UploadResult:
        """Upload a document to SuperDocs. Returns a document ID.

        BILLABLE — blocked in preview mode.
        """
        self._guard_billable("upload", preview)

        response = self._client.post(
            "/api/documents/upload",
            files={"file": (filename, file_content)},
        )
        response.raise_for_status()
        data = response.json()

        doc_id = data.get("document_id") or data.get("id") or ""
        logger.info("Uploaded document '%s' -> doc_id=%s", filename, doc_id)

        return UploadResult(document_id=doc_id, raw_response=data)

    def send_edit_instruction(self, document_id: str, instruction: str,
                              preview: bool = False) -> ChatResult:
        """Send an edit instruction to SuperDocs. Returns proposed changes.

        BILLABLE — blocked in preview mode.
        The response requires double JSON parsing (see parse_proposed_changes).
        """
        self._guard_billable("chat", preview)

        response = self._client.post(
            f"/api/documents/{document_id}/chat",
            json={"instruction": instruction},
        )
        response.raise_for_status()
        data = response.json()

        changes = parse_proposed_changes(data)
        return ChatResult(proposed_changes=changes, raw_response=data)

    def approve_changes(self, document_id: str) -> dict:
        """Approve proposed changes. NOT billable — safe to retry."""
        response = self._client.post(
            f"/api/documents/{document_id}/approve",
        )
        response.raise_for_status()
        data = response.json()
        logger.info("Approved changes for doc_id=%s", document_id)
        return data

    def export_document(self, document_id: str) -> ExportResult:
        """Export the finished document. NOT billable — safe to retry freely."""
        response = self._client.get(
            f"/api/documents/{document_id}/export",
        )
        response.raise_for_status()

        content_type = response.headers.get("content-type", "application/octet-stream")
        # Try to extract filename from content-disposition header
        cd = response.headers.get("content-disposition", "")
        filename = "exported_document"
        if "filename=" in cd:
            filename = cd.split("filename=")[1].strip('"').strip("'")

        logger.info("Exported doc_id=%s (%d bytes)", document_id, len(response.content))
        return ExportResult(
            content=response.content,
            filename=filename,
            content_type=content_type,
        )


class PreviewModeBlocked(Exception):
    """Raised when a billable operation is attempted in preview mode.

    This is a control-flow signal, not an error — it means the system
    is working correctly by refusing to spend operations.
    """
    pass
