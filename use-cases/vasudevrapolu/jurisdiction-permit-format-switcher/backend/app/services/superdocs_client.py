from typing import Any
import httpx
from app.core.config import settings

class SuperDocsClient:
    def __init__(self) -> None:
        self.base_url = settings.superdocs_base_url.rstrip("/")
        self.api_key = settings.superdocs_api_key

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def edit(self, *, session_id: str, message: str, document_html: str) -> dict[str, Any]:
        if not self.api_key:
            return {"document_changes": {"updated_html": document_html}, "response": "Local deterministic adapter used because no SuperDocs key is configured.", "superdocs_used": False}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"message": message, "session_id": session_id, "document_html": document_html, "approval_mode": "approve_all"}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self.base_url}/v1/chat", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return {**data, "superdocs_used": True}
