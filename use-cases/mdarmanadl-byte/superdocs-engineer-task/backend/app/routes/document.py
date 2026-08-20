import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.services.superdocs import superdocs_client


router = APIRouter(
    prefix="/api/documents",
    tags=["documents"],
)


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
):
    try:
        # Read uploaded file
        file_bytes = await file.read()

        content_type = (
            file.content_type
            or "application/octet-stream"
        )

        # Create a valid SuperDocs session ID
        session_id = f"task2-{uuid.uuid4()}"

        # --------------------------------
        # 1. Request upload URL
        # --------------------------------
        upload = await superdocs_client.create_upload(
            filename=file.filename,
            content_type=content_type,
            size_bytes=len(file_bytes),
        )

        upload_id = upload["upload_id"]
        upload_url = upload["upload_url"]

        # --------------------------------
        # 2. Upload actual file
        # --------------------------------
        await superdocs_client.upload_file_to_storage(
            upload_url=upload_url,
            file_bytes=file_bytes,
            content_type=content_type,
        )

        # --------------------------------
        # 3. Parse uploaded file
        # --------------------------------
        processed = await superdocs_client.process_upload(
            upload_id=upload_id,
            session_id=session_id,
            filename=file.filename,
        )

        return {
            "filename": file.filename,
            "size_bytes": len(file_bytes),
            "upload_id": upload_id,
            "session_id": session_id,
            "processed": processed,
        }

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )