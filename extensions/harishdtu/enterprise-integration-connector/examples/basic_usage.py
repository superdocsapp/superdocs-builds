"""
End-to-end usage example. NOT part of the test suite (tests/ mocks the HTTP
boundary and needs no key) -- this script makes real calls to
https://api.superdocs.app and requires a real SUPERDOCS_API_KEY.

Run:
    export SUPERDOCS_API_KEY=sk_...
    python examples/basic_usage.py
"""
import asyncio
import os

from connector import ConnectorConfig, JobWorker, LoggingCallbackDispatcher, SuperDocsHTTPClient
from connector.operations import edit_by_instruction, export_document, poll_for_completion, upload_document
from schemas.common import ExportFormat
from schemas.edit_by_instruction import EditByInstructionInput
from schemas.export import ExportInput
from schemas.poll import PollInput
from schemas.upload import UploadInput


async def main() -> None:
    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key:
        raise SystemExit("Set SUPERDOCS_API_KEY before running this example.")

    config = ConnectorConfig(api_key=api_key)
    client = SuperDocsHTTPClient(config)
    try:
        # 1. Upload a small starting document.
        upload_result = await upload_document(client, UploadInput(
            filename="draft.txt",
            content=b"This agreement is between Acme Corp and the Vendor.",
        ))
        print("Uploaded:", upload_result)

        # 2. Ask for an async edit.
        edit_result = await edit_by_instruction(client, EditByInstructionInput(
            session_id=upload_result.session_id,
            instruction="Add a standard 30-day payment terms clause.",
            run_async=True,
        ))
        print("Edit job started:", edit_result.job_id)

        # 3a. Poll manually once, just to show the shape...
        status = await poll_for_completion(client, PollInput(job_id=edit_result.job_id))
        print("Poll snapshot:", status.status)

        # 3b. ...or let a JobWorker run it to a terminal state with a callback.
        worker = JobWorker(config, client)
        dispatcher = LoggingCallbackDispatcher()
        task = worker.start_background(edit_result.job_id, dispatcher)
        await task
        print("Callback events received:", dispatcher.received)

        # 4. Export the result.
        export_result = await export_document(client, ExportInput(
            session_id=upload_result.session_id, format=ExportFormat.pdf,
        ))
        print(f"Exported {export_result.filename} ({export_result.size_bytes} bytes, "
              f"{len(export_result.warnings)} warning(s))")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
