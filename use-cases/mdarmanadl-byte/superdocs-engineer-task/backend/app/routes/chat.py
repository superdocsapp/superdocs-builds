from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.superdocs import superdocs_client


router = APIRouter(
    prefix="/api/chat",
    tags=["chat"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    document_html: str | None = None
    approval_mode: str = "approve_all"
    document_id: str | None = None


@router.post("")
async def chat(request: ChatRequest):
    try:
        result = await superdocs_client.chat(
            session_id=request.session_id,
            message=request.message,
            document_html=request.document_html,
            approval_mode=request.approval_mode,
            document_id=request.document_id,
        )

        return result

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )

@router.post("/async")
async def chat_async(request: ChatRequest):
    try:
        return await superdocs_client.chat_async(
            session_id=request.session_id,
            message=request.message,
            document_html=request.document_html,
            approval_mode=request.approval_mode,
            document_id=request.document_id,
        )

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )

@router.get("/job/{job_id}")
async def get_chat_job(job_id: str):
    try:

       result= await superdocs_client.get_job(job_id)
       metadata = result.get("metadata") or {}
    #    print("metadata" , metadata)
       if metadata:
            changes = metadata.get("pending_changes", [])
            if changes:
                for change in changes:
                    print(f"Change ID: {change.get('change_id')}")


    #    print("GET JOB RESULT:", result.metadata.get("pending_changes")[0].get("change_id") if result.metadata.get("pending_changes") else "No pending changes")
       return result

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )

@router.post("/job/{job_id}/cancel")
async def cancel_chat_job(job_id: str):
    try:
        
        result= await superdocs_client.cancel_job(job_id)
        
        return result

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )
@router.get("/alljob")
async def list_jobs():

    result= await superdocs_client.list_jobs()
    for job in result["jobs"]:
        print(f"ID: {job['job_id']} | Status: {job['status']}")
    return result

@router.get("/active")
async def get_active_job(session_id: str):
    try:
        for status in ["pending", "in_progress", "awaiting_approval"]:
            response = await superdocs_client.list_jobs(
                status=status,
                limit=50,
            )

            print("LIST JOBS RESPONSE:", response)

            jobs = response

            # If API wraps jobs inside a key
            if isinstance(response, dict):
                jobs = (
                    response.get("jobs")
                    or response.get("data")
                    or []
                )

            if not isinstance(jobs, list):
                continue

            for job in jobs:
                if (
                    isinstance(job, dict)
                    and job.get("session_id") == session_id
                ):
                    return job

        return None

    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )