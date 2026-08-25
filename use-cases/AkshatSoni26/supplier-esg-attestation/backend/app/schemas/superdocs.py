import json
import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class SuperDocsUploadResponse(BaseModel):
    document_id: str = Field(default_factory=lambda: f"sd-doc-{uuid.uuid4().hex[:8]}")
    filename: str = "document.md"
    file_size_bytes: int = 0
    content_preview: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    html: str | None = None


class SuperDocsChatRequest(BaseModel):
    document_id: str
    instruction: str
    context: str | None = None


class SuperDocsDiffCard(BaseModel):
    diff_id: str = Field(default_factory=lambda: f"diff-{uuid.uuid4().hex[:6]}")
    target_section: str = "General"
    original_text: str = ""
    suggested_text: str = ""
    explanation: str = ""


class SuperDocsChatResponse(BaseModel):
    job_id: str = Field(default_factory=lambda: f"sd-job-{uuid.uuid4().hex[:8]}")
    document_id: str
    status: str = "awaiting_approval"  # in_progress, completed, awaiting_approval
    # In SuperDocs, proposed change raw content can be a double JSON encoded string.
    raw_proposed_changes: str | None = None
    parsed_diffs: list[SuperDocsDiffCard] = Field(default_factory=list)

    @classmethod
    def parse_raw_changes(cls, raw_content: str | None) -> list[SuperDocsDiffCard]:
        """Safely unpack the SuperDocs 2-step JSON string encoding for proposed changes."""
        if not raw_content:
            return []
        try:
            # Step 1: parse top level if string
            data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
            # Step 2: if double-string encoded
            if isinstance(data, str):
                data = json.loads(data)
            
            diffs: list[SuperDocsDiffCard] = []
            if isinstance(data, list):
                for item in data:
                    diffs.append(SuperDocsDiffCard(
                        diff_id=item.get("diff_id") or f"diff-{uuid.uuid4().hex[:6]}",
                        target_section=item.get("target_section") or "General",
                        original_text=item.get("original_text", ""),
                        suggested_text=item.get("suggested_text", ""),
                        explanation=item.get("explanation") or item.get("rationale") or ""
                    ))
            elif isinstance(data, dict) and "diffs" in data:
                for item in data["diffs"]:
                    diffs.append(SuperDocsDiffCard(
                        diff_id=item.get("diff_id") or f"diff-{uuid.uuid4().hex[:6]}",
                        target_section=item.get("target_section") or "General",
                        original_text=item.get("original_text", ""),
                        suggested_text=item.get("suggested_text", ""),
                        explanation=item.get("explanation", "")
                    ))
            return diffs
        except (json.JSONDecodeError, TypeError, KeyError, ValueError):
            return []


class SuperDocsApproveRequest(BaseModel):
    document_id: str
    approved_diff_ids: list[str]
    rejected_diff_ids: list[str] = Field(default_factory=list)


class SuperDocsExportResponse(BaseModel):
    document_id: str
    export_format: str  # docx, pdf, md, html
    download_url: str
    file_bytes_size: int
