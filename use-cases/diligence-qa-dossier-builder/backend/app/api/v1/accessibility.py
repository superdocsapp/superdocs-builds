from fastapi import APIRouter, UploadFile, File, HTTPException, status
from typing import Dict, Optional
from pydantic import BaseModel

from backend.app.services.accessibility import AccessibilityService, AccessibilityAudit, AccessibilityRemediationResponse

router = APIRouter(prefix="/accessibility", tags=["accessibility"])

class TextCheckRequest(BaseModel):
    text: str

class TextRemediateRequest(BaseModel):
    text: str
    alt_text_overrides: Dict[str, str]

@router.post("/check", response_model=AccessibilityAudit)
async def check_document_accessibility(payload: TextCheckRequest):
    """
    Scans a raw markdown or text string for accessibility problems.
    """
    service = AccessibilityService()
    return service.audit_document(payload.text)

@router.post("/check-file", response_model=AccessibilityAudit)
async def check_file_accessibility(file: UploadFile = File(...)):
    """
    Uploads a markdown/text file and scans it for accessibility problems.
    """
    service = AccessibilityService()
    try:
        content_bytes = await file.read()
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = content_bytes.decode("cp1252", errors="replace")
        return service.audit_document(text)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse uploaded file: {str(e)}"
        )

@router.post("/remediate", response_model=AccessibilityRemediationResponse)
async def remediate_document_accessibility(payload: TextRemediateRequest):
    """
    Applies heading and user-supplied alt-text fixes, returning semantic HTML and report.
    """
    service = AccessibilityService()
    return service.remediate_document(payload.text, payload.alt_text_overrides)
