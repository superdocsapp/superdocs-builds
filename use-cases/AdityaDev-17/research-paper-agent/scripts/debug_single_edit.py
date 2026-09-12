"""Isolated debug: create a 1-section document, edit it once, print the
FULL response, then pull the raw HTML back via export to see what
SuperDocs' document actually contains server-side.

Usage:
    python scripts\\debug_single_edit.py
"""
import json
import uuid
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import SUPERDOCS_API_KEY, SUPERDOCS_MCP_URL
from src.mcp_client import SuperDocsMCPClient


def main():
    with SuperDocsMCPClient(url=SUPERDOCS_MCP_URL, api_key=SUPERDOCS_API_KEY) as client:
        session_id = f"debug-single-edit-{uuid.uuid4()}"
        print(f"Using fresh session: {session_id}\n")

        print("=" * 60)
        print("STEP 1: create session with one-section skeleton")
        print("=" * 60)
        html_after_create = client.create_session_with_document(
            session_id, "<h2>Abstract</h2><p>[Placeholder: content for the Abstract section will be added here.]</p>"
        )
        print(f"HTML after create:\n{html_after_create}\n")

        print("=" * 60)
        print("STEP 2: edit that section (raw call, full response)")
        print("=" * 60)
        raw_response = client._call("chat", {
            "session_id": session_id,
            "message": (
                "Replace the placeholder paragraph directly under the 'Abstract' "
                "heading (it starts with '[Placeholder:') with the following text, exactly "
                "as given, and do not modify any other section:\n\n"
                "This is a test sentence that should appear under the Abstract heading."
            ),
        })
        print(json.dumps(raw_response, indent=2))

        doc_changes = raw_response["document_changes"]
        if doc_changes.get("requires_approval"):
            print("\n" + "=" * 60)
            print("STEP 2b: approve the pending change")
            print("=" * 60)
            job_id = doc_changes["job_id"]
            change_id = doc_changes["pending_changes"][0]["change_id"]
            approve_response = client._call("approve_change", {
                "session_id": session_id,
                "job_id": job_id,
                "change_id": change_id,
                "approved": True,
            })
            print(json.dumps(approve_response, indent=2))

            print("\n" + "=" * 60)
            print("STEP 2c: poll get_job for the final result")
            print("=" * 60)
            import time
            for attempt in range(10):
                job_result = client._call("get_job", {"job_id": job_id})
                status = job_result.get("status")
                print(f"Poll {attempt}: status={status}")
                if status == "completed":
                    print(json.dumps(job_result, indent=2))
                    break
                time.sleep(1)

        print("=" * 60)
        print("STEP 3: export as HTML and check what's actually stored")
        print("=" * 60)
        exported_path = client.export_document(session_id, format="html")
        print(f"Exported to: {exported_path}")
        exported_content = Path(exported_path).read_text(encoding="utf-8")
        print(f"\nExported file content:\n{exported_content}")


if __name__ == "__main__":
    main()