import asyncio
import json
from typing import Any

from app.services.superdocs_service import SuperDocsClient


async def main() -> None:
    client = SuperDocsClient()

    session_id = "daily-field-report-hitl-test"

    document_html = """
    <h1>Daily Field Report</h1>
    <p>18 workers were onsite today.</p>
    <p>Concrete work was completed in Zone A.</p>
    """

    print("1. Starting SuperDocs approval job...")

    job_response = await client.start_approval_job(
        session_id=session_id,
        message=(
            "Rewrite the title to make it more professional. "
            "Do not change any other content."
        ),
        document_html=document_html,
    )

    print("Job response:")
    print(json.dumps(job_response, indent=2))

    job_id = job_response["job_id"]

    print(f"\nJob ID: {job_id}")
    print("2. Checking job status...")

    for attempt in range(30):
        job = await client.get_job(job_id)

        status = job.get("status")

        print(f"Attempt {attempt + 1}: {status}")

        if status == "awaiting_approval":
            metadata: dict[str, Any] = job.get("metadata", {})

            print("\nApproval required.")
            print(
                json.dumps(
                    metadata.get("pending_changes"),
                    indent=2,
                )
            )

            pending_changes = metadata.get("pending_changes", [])

            if not pending_changes:
                print("No pending changes found.")
                return

            changes = [
                {
                    "change_id": change["change_id"],
                    "approved": True,
                }
                for change in pending_changes
            ]

            print("\n3. Approving proposed changes...")

            approval_response = await client.approve_changes(
                session_id=session_id,
                job_id=job_id,
                approved=True,
                changes=changes,
            )

            print("Approval response:")
            print(json.dumps(approval_response, indent=2))

        elif status == "completed":
            print("\n4. Job completed successfully.")

            print(
                json.dumps(
                    job,
                    indent=2,
                )
            )

            return

        elif status == "failed":
            print("\nJob failed:")
            print(json.dumps(job, indent=2))
            return

        await asyncio.sleep(2)

    print("\nTimed out waiting for the SuperDocs job.")


if __name__ == "__main__":
    asyncio.run(main())