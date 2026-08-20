from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.export_service import export_service


router = APIRouter(
    prefix="/api/export",
    tags=["export"],
)


class ExportRequest(BaseModel):
    session_id: str
    format: str
    document_id: str | None = None


@router.post("")
async def export_document(request: ExportRequest):
    try:
        result = await export_service.export_document(
            session_id=request.session_id,
            export_format=request.format,
            document_id=request.document_id,
        )

        return Response(
            content=result["content"],
            media_type=result["content_type"],
            headers={
                "Content-Disposition": (
                    result["filename"]
                    or f'attachment; filename="document.{request.format}"'
                )
            },
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )