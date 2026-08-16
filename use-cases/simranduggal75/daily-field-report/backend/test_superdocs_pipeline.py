import asyncio
import json
import uuid
from pathlib import Path

from app.services.report_pipeline import start_superdocs_workflow
from app.services.superdocs_service import SuperDocsClient


async def main():
    reports = list(
        Path("storage/reports").glob(
            "*/daily_field_report.html"
        )
    )

    if not reports:
        raise RuntimeError(
            "No generated Daily Field Report HTML found."
        )

    html_path = max(
        reports,
        key=lambda path: path.stat().st_mtime,
    )

    report_id = html_path.parent.name

    print(f"Using report: {html_path}")
    print(f"Report ID: {report_id}")

    test_report_id = (
        f"{report_id}-{uuid.uuid4().hex[:8]}"
    )

    # ---------------------------------------------------------
    # 1. Start SuperDocs workflow
    # ---------------------------------------------------------

    result = await start_superdocs_workflow(
        report_id=test_report_id,
        html_path=html_path,
    )

    print("\nSuperDocs workflow started:")
    print(
        json.dumps(
            result,
            indent=2,
            default=str,
        )
    )

    job = result["job"]

    if job["status"] != "awaiting_approval":
        raise RuntimeError(
            f"Expected awaiting_approval, "
            f"got {job['status']}"
        )

    pending_changes = job["metadata"]["pending_changes"]

    print(
        f"\nFound {len(pending_changes)} pending changes."
    )

    # ---------------------------------------------------------
    # 2. Approve proposed changes
    # ---------------------------------------------------------

    superdocs = SuperDocsClient()

    approval_result = await superdocs.approve_changes(
        session_id=result["session_id"],
        job_id=result["job_id"],
        approved=True,
        changes=pending_changes,
    )

    print("\nApproval result:")
    print(
        json.dumps(
            approval_result,
            indent=2,
            default=str,
        )
    )

    # ---------------------------------------------------------
    # 3. Wait for approval job to finish
    # ---------------------------------------------------------

    print("\nWaiting for SuperDocs job to complete...")

    final_job = None

    for attempt in range(30):
        await asyncio.sleep(2)

        final_job = await superdocs.get_job(
            result["job_id"]
        )

        status = final_job.get("status")

        print(
            f"Attempt {attempt + 1}: {status}"
        )

        if status in {
            "completed",
            "failed",
            "cancelled",
        }:
            break

    if not final_job:
        raise RuntimeError(
            "Unable to retrieve final SuperDocs job status."
        )

    if final_job.get("status") != "completed":
        raise RuntimeError(
            "SuperDocs approval job did not complete: "
            f"{final_job}"
        )

    # ---------------------------------------------------------
    # 4. Export approved document
    # ---------------------------------------------------------

    print("\nExporting approved document...")

    export_result = await superdocs.export_document(
        session_id=result["session_id"],
        format="pdf",
        filename="daily-field-report",
    )

    print("\nExport result:")
    print(
        json.dumps(
            export_result,
            indent=2,
            default=str,
        )
    )

    # ---------------------------------------------------------
    # 5. Verify exported file
    # ---------------------------------------------------------

    export_path = Path(
        export_result["path"]
    )

    if not export_path.exists():
        raise RuntimeError(
            f"Export reported success but file "
            f"does not exist: {export_path}"
        )

    if export_path.stat().st_size == 0:
        raise RuntimeError(
            f"Exported PDF is empty: {export_path}"
        )

    print(
        f"\nPDF verified: {export_path}"
    )

    print(
        "\nFull SuperDocs pipeline completed successfully."
    )


if __name__ == "__main__":
    asyncio.run(main())