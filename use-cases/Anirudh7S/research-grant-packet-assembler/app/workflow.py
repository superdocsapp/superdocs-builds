from pathlib import Path
from typing import Any, Dict
import re
import time

from app.page_limits import enforce_page_limit_locally
from app.pipeline import run_grant_assembly
from app.superdocs import SuperDocsClient


def _approve_pending_changes(
    client: SuperDocsClient,
    session_id: str,
    job: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Approve all pending HITL changes returned by a SuperDocs job.
    """

    metadata = job.get("metadata", {})
    pending_changes = metadata.get(
        "pending_changes",
        [],
    )

    approvals = []

    for change in pending_changes:
        approval = client.approve_change(
            session_id=session_id,
            job_id=job["job_id"],
            change_id=change["change_id"],
            approved=True,
        )

        approvals.append(approval)

    return {
        "approved_count": len(approvals),
        "approvals": approvals,
    }


def wait_for_job(
    client: SuperDocsClient,
    job_id: str,
    max_attempts: int = 30,
    poll_seconds: int = 5,
) -> Dict[str, Any]:
    """
    Poll an asynchronous SuperDocs job until it reaches a terminal state.

    The bounded polling loop prevents an integration from waiting forever.
    """

    for _ in range(max_attempts):
        job = client.get_job(job_id)

        status = job.get("status")

        if status in {
            "completed",
            "failed",
            "cancelled",
            "awaiting_approval",
        }:
            return job

        time.sleep(poll_seconds)

    raise RuntimeError(
        f"SuperDocs job {job_id} did not finish within "
        f"{max_attempts * poll_seconds} seconds."
    )


def _html_to_text(html: str) -> str:
    """
    Convert SuperDocs HTML into plain text for local page estimation.
    """

    text = re.sub(
        r"<[^>]+>",
        " ",
        html,
    )

    text = (
        text
        .replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .strip()
    )

    return text


def _export_superdocs_document(
    client: SuperDocsClient,
    session_id: str,
    updated_html: str,
    document_path: Path,
) -> Dict[str, Any]:
    """
    Export the final SuperDocs HTML as a DOCX file.
    """

    export_path = (
        document_path.parent
        / f"{document_path.stem}_superdocs_export.docx"
    )

    exported_bytes = client.export_document(
        session_id=session_id,
        html=updated_html,
        filename=export_path.name,
    )

    export_path.write_bytes(
        exported_bytes
    )

    return {
        "exported": True,
        "export_path": str(export_path),
        "export_filename": export_path.name,
        "export_size_bytes": len(exported_bytes),
    }


def run_page_limit_workflow(
    client: SuperDocsClient,
    document_path: Path,
    document_type: str,
    page_limit: int,
) -> Dict[str, Any]:
    """
    Upload a document to SuperDocs and request prose tightening when
    the local page-limit check says editing is required.

    The workflow performs:

    1. Local page-limit check.
    2. SuperDocs upload.
    3. Async AI editing.
    4. HITL approval, including multiple approval batches.
    5. Final document retrieval.
    6. Local page-limit recheck.
    7. DOCX export.
    """

    original_text = document_path.read_text(
        encoding="utf-8"
    )

    before_check = enforce_page_limit_locally(
        document_type,
        original_text,
        page_limit,
    )

    result: Dict[str, Any] = {
        "document": str(document_path),
        "document_type": document_type,
        "page_limit": page_limit,
        "before": before_check,
        "edited": False,
        "approval": None,
        "job": None,
        "job_after_approval": None,
        "updated_html": None,
        "after": None,
        "export": None,
    }

    # ---------------------------------------------------------
    # If the document already fits, there is no reason to call
    # SuperDocs.
    # ---------------------------------------------------------

    if not before_check["requires_superdocs_edit"]:
        result["after"] = before_check
        return result

    # ---------------------------------------------------------
    # 1. Create SuperDocs session
    # ---------------------------------------------------------

    session = client.init_session()

    session_id = session["session_id"]

    result["session_id"] = session_id

    # ---------------------------------------------------------
    # 2. Upload document
    # ---------------------------------------------------------

    upload = client.upload_document(
        str(document_path),
        session_id,
    )

    result["document_id"] = upload.get(
        "document_id"
    )

    result["upload"] = upload

    # ---------------------------------------------------------
    # 3. Request async page-limit editing
    # ---------------------------------------------------------

    job = client.chat_async(
        session_id,
        before_check["instruction"],
        approval_mode="ask_every_time",
    )

    job_id = job["job_id"]

    result["job_id"] = job_id

    # ---------------------------------------------------------
    # 4. Wait for initial AI processing / HITL state
    # ---------------------------------------------------------

    job_result = wait_for_job(
        client,
        job_id,
    )

    result["job"] = job_result

    # ---------------------------------------------------------
    # 5. Approve ALL HITL batches until SuperDocs completes
    # ---------------------------------------------------------

    total_approved = 0
    approval_batches = []

    while job_result.get("status") == "awaiting_approval":

        approval = _approve_pending_changes(
            client,
            session_id,
            job_result,
        )

        approved_count = approval.get(
            "approved_count",
            0,
        )

        total_approved += approved_count

        approval_batches.append(
            approval
        )

        # Safety guard:
        # If SuperDocs asks for approval but returns no changes,
        # do not loop forever.
        if approved_count == 0:
            result["approval"] = {
                "approved_count": total_approved,
                "batches": approval_batches,
                "error": (
                    "SuperDocs requested approval but returned "
                    "no pending changes."
                ),
            }

            result["after"] = {
                "status": "superdocs_failed",
                "error": (
                    "SuperDocs requested approval but returned "
                    "no pending changes."
                ),
            }

            return result

        # Wait for SuperDocs to continue processing.
        job_result = wait_for_job(
            client,
            job_id,
        )

    result["approval"] = {
        "approved_count": total_approved,
        "batch_count": len(approval_batches),
        "batches": approval_batches,
    }

    result["job_after_approval"] = job_result

    # ---------------------------------------------------------
    # 6. Handle failed/cancelled jobs
    # ---------------------------------------------------------

    if job_result.get("status") != "completed":
        result["after"] = {
            "status": "superdocs_failed",
            "error": job_result.get("error"),
            "job_status": job_result.get("status"),
        }

        return result

    # ---------------------------------------------------------
    # 7. Extract final HTML
    # ---------------------------------------------------------

    updated_html = (
        job_result
        .get("result", {})
        .get("document_changes", {})
        .get("updated_html", "")
    )

    result["updated_html"] = updated_html

    if not updated_html:
        result["after"] = {
            "status": "superdocs_no_output",
            "error": "SuperDocs returned no updated HTML.",
        }

        return result

    # ---------------------------------------------------------
    # 8. Re-check page limit
    # ---------------------------------------------------------

    updated_text = _html_to_text(
        updated_html
    )

    after_check = enforce_page_limit_locally(
        document_type,
        updated_text,
        page_limit,
    )

    result["edited"] = True
    result["after"] = after_check

    # ---------------------------------------------------------
    # 9. Export final SuperDocs document
    # ---------------------------------------------------------

    if after_check["within_limit"]:
        result["export"] = _export_superdocs_document(
            client=client,
            session_id=session_id,
            updated_html=updated_html,
            document_path=document_path,
        )
    else:
        result["export"] = {
            "exported": False,
            "reason": (
                "Final document still exceeds the page limit."
            ),
        }

    return result


def run_superdocs_workflow(
    grant_directory: str | Path,
) -> Dict[str, Any]:
    """
    Run the complete local grant + SuperDocs workflow.
    """

    grant_directory = Path(
        grant_directory
    )

    # ---------------------------------------------------------
    # 1. Build and validate grant package
    # ---------------------------------------------------------

    assembly = run_grant_assembly(
        grant_directory
    )

    validation = assembly["validation"]

    # Never send an invalid grant package to SuperDocs.
    if not validation["valid"]:
        return {
            "status": "validation_failed",
            "validation": validation,
            "grant_package": assembly["grant_package"],
            "output_path": assembly["output_path"],
        }

    # ---------------------------------------------------------
    # 2. Create SuperDocs client
    # ---------------------------------------------------------

    client = SuperDocsClient()

    # ---------------------------------------------------------
    # 3. Run research-narrative page-limit workflow
    # ---------------------------------------------------------

    research_narrative_path = (
        grant_directory
        / "research_narrative.txt"
    )

    page_limit_result = run_page_limit_workflow(
        client=client,
        document_path=research_narrative_path,
        document_type="research_narrative",
        page_limit=5,
    )

    return {
        "status": "completed",
        "validation": validation,
        "grant_package": assembly["grant_package"],
        "biosketches": assembly.get(
            "biosketches",
            [],
        ),
        "output_path": assembly["output_path"],
        "page_limit": page_limit_result,
    }