from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.report_intake import STORAGE_DIR, create_report
from app.services.report_pipeline import (
    ReportPipelineError,
    process_report,
    wait_for_superdocs_approval,
)
from app.services.report_store import update_metadata
from app.services.superdocs_service import SuperDocsClient


router = APIRouter(
    prefix="/api/v1/reports",
    tags=["reports"],
)


class ApproveReportRequest(BaseModel):
    job_id: str = Field(
        ...,
        description="SuperDocs approval job ID",
    )

    changes: list[dict] = Field(
        default_factory=list,
        description=(
            "Proposed SuperDocs changes to approve. "
            "Each change must contain a change_id."
        ),
    )


@router.post("")
async def create_field_report(
    notes: Annotated[str | None, Form()] = None,
    project: Annotated[
        str | None,
        Form(
            description=(
                "Optional explicit project name/identifier "
                "(e.g. from a dropdown). Useful for photo-only "
                "reports with nothing to extract a project from."
            )
        ),
    ] = None,
    photos: Annotated[
        list[UploadFile],
        File(description="Site photos"),
    ] = [],
):
    """
    Create a Daily Field Report.

    Flow:

    notes/photos
        ↓
    structured report
        ↓
    photo analysis + captions
        ↓
    HTML report
        ↓
    SuperDocs upload
        ↓
    AI edit
        ↓
    awaiting_approval
    """

    try:
        # ---------------------------------------------------------
        # Step 1: Persist incoming notes and photos
        # ---------------------------------------------------------

        intake = await create_report(
            notes=notes,
            photos=photos,
            project=project,
        )

        # ---------------------------------------------------------
        # Step 2: Generate report + start SuperDocs workflow
        # ---------------------------------------------------------

        pipeline_result = await process_report(
            report_id=intake["report_id"],
            report_dir=Path(intake["report_dir"]),
            notes=notes,
            photo_filenames=intake["photos"],
            explicit_project=project,
        )

        # ---------------------------------------------------------
        # Step 3: Return report + approval information
        # ---------------------------------------------------------

        return {
            "report_id": intake["report_id"],
            "status": pipeline_result["status"],
            "intake": {
                "has_notes": intake["has_notes"],
                "photo_count": intake["photo_count"],
                "photos": intake["photos"],
            },
            "report": pipeline_result["report_data"],
            "photo_captions": pipeline_result[
                "photo_captions"
            ],
            "photo_analysis": pipeline_result[
                "photo_analysis"
            ],
            "html_path": pipeline_result["html_path"],
            "superdocs": pipeline_result["superdocs"],
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except ReportPipelineError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to create field report.",
        ) from exc


@router.post("/{report_id}/approve")
async def approve_field_report(
    report_id: str,
    request: ApproveReportRequest,
):
    """
    Approve proposed SuperDocs changes and export the
    completed Daily Field Report as a PDF.

    Flow:

    awaiting_approval
        ↓
    human approval
        ↓
    SuperDocs completion
        ↓
    PDF export
    """

    report_dir = STORAGE_DIR / report_id

    try:
        # ---------------------------------------------------------
        # Step 1: Create SuperDocs client/session
        # ---------------------------------------------------------

        superdocs = SuperDocsClient()

        session_id = (
            f"daily-report-{report_id}"
        )

        # ---------------------------------------------------------
        # Step 2: Approve proposed changes
        # ---------------------------------------------------------

        approval_result = await superdocs.approve_changes(
            session_id=session_id,
            job_id=request.job_id,
            approved=True,
            changes=request.changes,
        )

        if approval_result.get("status") != "ok":
            raise ReportPipelineError(
                "SuperDocs approval was not successful."
            )

        # ---------------------------------------------------------
        # Step 3: Wait for approved changes to complete
        # ---------------------------------------------------------

        final_job = await wait_for_superdocs_approval(
            superdocs=superdocs,
            job_id=request.job_id,
        )

        final_status = final_job.get("status")

        if final_status != "completed":
            raise ReportPipelineError(
                "SuperDocs approval did not complete. "
                f"Final status: {final_status}"
            )

        update_metadata(report_dir, status="approved")

        # ---------------------------------------------------------
        # Step 4: Export approved report as PDF
        # ---------------------------------------------------------

        export_result = await superdocs.export_document(
            session_id=session_id,
            format="pdf",
            filename=f"daily-field-report-{report_id}",
        )

        if export_result.get("status") != "exported":
            raise ReportPipelineError(
                "Approved report could not be exported."
            )

        update_metadata(report_dir, status="exported")

        # ---------------------------------------------------------
        # Step 5: Return final result
        # ---------------------------------------------------------

        return {
            "report_id": report_id,
            "status": "report_exported",
            "approval": approval_result,
            "job": {
                "job_id": request.job_id,
                "status": final_status,
            },
            "export": export_result,
        }

    except ReportPipelineError as exc:
        update_metadata(
            report_dir,
            status="failed",
            failure_reason=str(exc),
        )
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        update_metadata(
            report_dir,
            status="failed",
            failure_reason=str(exc),
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to approve and export field report.",
        ) from exc


@router.get("/{report_id}/download")
async def download_field_report(report_id: str):
    """
    Serve the exported PDF for a report, so the browser has something
    to actually download - export_document() only returns a
    server-side filesystem path, not a fetchable URL.
    """

    export_path = (
        Path("storage/exports") / f"daily-field-report-{report_id}.pdf"
    )

    if not export_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No exported PDF found for this report yet. "
                "Approve the proposed changes first."
            ),
        )

    return FileResponse(
        export_path,
        media_type="application/pdf",
        filename=export_path.name,
    )