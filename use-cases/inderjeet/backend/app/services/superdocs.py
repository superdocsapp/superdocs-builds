import json
import logging
import httpx
from typing import Dict, Any, List, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

class SuperDocsClient:
    """
    Python SDK Client wrapper for the SuperDocs document editing REST surface.
    Integrates /upload, /chat, /approve, and /export endpoints.
    """
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or settings.SUPERDOCS_API_KEY
        self.base_url = base_url or settings.SUPERDOCS_BASE_URL
        self.headers = {
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
            "Content-Type": "application/json"
        }
        self.mock_mode = self.api_key is None or self.api_key == "" or settings.SMALL_SAMPLE_MODE

    def upload_document(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        """
        Uploads a document to the SuperDocs platform.
        POST /upload (Multipart file upload)
        """
        if self.mock_mode:
            logger.info(f"[MOCK] Uploading document: {filename}")
            return {"document_id": f"mock_doc_{uuid_short()}", "status": "success"}

        files = {"file": (filename, file_content)}
        # Remove JSON content type for multipart request
        headers = {k: v for k, v in self.headers.items() if k.lower() != "content-type"}
        
        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}/upload",
                headers=headers,
                files=files,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()

    def send_edit_instruction(self, document_id: str, instruction: str) -> Dict[str, Any]:
        """
        Sends an instruction to modify a target section.
        POST /chat
        """
        if self.mock_mode:
            logger.info(f"[MOCK] Editing {document_id} with instruction: {instruction}")
            # Mock proposed change payload (contains stringified JSON diff card)
            mock_diff = {
                "changes": [
                    {
                        "id": "change_01",
                        "target_section": "Flight Details",
                        "original_text": "Flight AA123 departs at 10:00 AM",
                        "proposed_text": "Flight AA456 departs at 2:30 PM",
                        "reason": "Re-routing due to flight cancellation"
                    }
                ]
            }
            # The API returns proposed-change content as a JSON-encoded string that needs a second parse
            return {
                "document_id": document_id,
                "status": "awaiting_approval",
                "proposed_changes": json.dumps(mock_diff)
            }

        payload = {
            "document_id": document_id,
            "instruction": instruction
        }
        
        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}/chat",
                headers=self.headers,
                json=payload,
                timeout=120.0
            )
            response.raise_for_status()
            data = response.json()
            
            # Guidelines note: proposed-change content arrives as a JSON-encoded string and needs a second parse.
            # We handle it here so downstream logic gets a cleanly parsed dict/object.
            if "proposed_changes" in data and isinstance(data["proposed_changes"], str):
                try:
                    data["proposed_changes"] = json.loads(data["proposed_changes"])
                except Exception as e:
                    logger.error(f"Failed to double-parse proposed_changes: {e}")
            
            return data

    def approve_changes(self, document_id: str, approved_change_ids: List[str]) -> Dict[str, Any]:
        """
        Commits chosen changes into the document session.
        POST /approve
        """
        if self.mock_mode:
            logger.info(f"[MOCK] Approving changes {approved_change_ids} on {document_id}")
            return {"document_id": document_id, "status": "committed", "committed_changes": approved_change_ids}

        payload = {
            "document_id": document_id,
            "approved_change_ids": approved_change_ids
        }
        
        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}/approve",
                headers=self.headers,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()

    def export_file(self, document_id: str, format_type: str = "pdf") -> bytes:
        """
        Exports the final approved document in specified format.
        POST /export
        """
        if self.mock_mode:
            logger.info(f"[MOCK] Exporting document {document_id} as {format_type}")
            return b"MOCK_EXPORTED_FILE_CONTENT"

        payload = {
            "document_id": document_id,
            "format": format_type
        }
        
        with httpx.Client() as client:
            response = client.post(
                f"{self.base_url}/export",
                headers=self.headers,
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            return response.content

def uuid_short() -> str:
    import uuid
    return uuid.uuid4().hex[:8]
