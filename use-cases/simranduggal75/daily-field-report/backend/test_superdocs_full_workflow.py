import asyncio
import json
import time
from pathlib import Path

from app.services.superdocs_service import SuperDocsClient


async def main() -> None:
    html_path = Path("sample_upload_report.html")

    if not html_path.exists():
        raise FileNotFoundError(
            "sample_upload_report.html not found. "
            "Run test_superdocs_document.py first."
        )

    client = SuperDocsClient()

    session_id = "daily-field-full-workflow-test"

    # ---------------------------------------------------------
    # 1. Upload the generated document
    # ---------------------------------------------------------

    print("1. Uploading document...")

    upload_result = await client.upload_document(
        session_id=session_id,
        file_path=html_path,
    )

    print(
        json.dumps(
            upload_result,
            indent=2,
        )
    )

    # ---------------------------------------------------------
    # 2. Start AI edit requiring approval
    # ---------------------------------------------------------

    print("\n2. Starting approval job...")

    job_result = await client.start_approval_job(
        session_id=session_id,
        message=(
            "Rewrite the document title to make it more "
            "professional. Do not change any other content."
        ),
    )

    job_id = job_result["job_id"]

    print(
        json.dumps(
            job_result,
            indent=2,
        )
    )

    # ---------------------------------------------------------
    # 3. Poll until approval is required
    # ---------------------------------------------------------

    print("\n3. Waiting for AI proposal...")

    approval_changes = None

    for attempt in range(1, 20):
        job = await client.get_job(job_id)

        status = job.get("status")

        print(
            f"Attempt {attempt}: {status}"
        )

        if status == "awaiting_approval":
            result = job.get("result") or {}

            approval_changes = (
                result.get("document_changes", {})
                .get("pending_changes")
            )

            if not approval_changes:
                approval_changes = (
                    job.get("metadata", {})
                    .get("pending_changes")
                )

            break

        if status in {
            "completed",
            "failed",
            "cancelled",
        }:
            print(
                json.dumps(
                    job,
                    indent=2,
                )
            )
            return

        await asyncio.sleep(2)

    if not approval_changes:
        raise RuntimeError(
            "SuperDocs reached awaiting_approval but "
            "no pending changes were returned."
        )

    print("\nProposed changes:")
    print(
        json.dumps(
            approval_changes,
            indent=2,
        )
    )

    # ---------------------------------------------------------
    # 4. Approve the proposed changes
    # ---------------------------------------------------------

    print("\n4. Approving changes...")

    approval_result = await client.approve_changes(
        session_id=session_id,
        job_id=job_id,
        approved=True,
        changes=approval_changes,
    )

    print(
        json.dumps(
            approval_result,
            indent=2,
        )
    )

    # ---------------------------------------------------------
    # 5. Wait for completion
    # ---------------------------------------------------------

    print("\n5. Waiting for completion...")

    final_job = None

    for attempt in range(1, 20):
        final_job = await client.get_job(job_id)

        status = final_job.get("status")

        print(
            f"Attempt {attempt}: {status}"
        )

        if status == "completed":
            break

        if status in {
            "failed",
            "cancelled",
        }:
            raise RuntimeError(
                json.dumps(
                    final_job,
                    indent=2,
                )
            )

        await asyncio.sleep(2)

    if not final_job or final_job.get("status") != "completed":
        raise RuntimeError(
            "SuperDocs job did not complete."
        )

    # ---------------------------------------------------------
    # 6. Export approved document
    # ---------------------------------------------------------

    print("\n6. Exporting approved document...")

    export_result = await client.export_document(
        session_id=session_id,
        format="pdf",
        filename="daily-field-report",
    )

    print(
        json.dumps(
            export_result,
            indent=2,
        )
    )

    print("\nFull SuperDocs workflow completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())