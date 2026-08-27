import base64
import json
from superdocs_client import (
    upload_document,
    start_chat_async,
    wait_for_job,
    get_pending_changes,
    approve_changes,
    export_document,
    resolve_any_pending_approval,
)

SESSION_ID = "review-assembler-test-2"

resolve_any_pending_approval(SESSION_ID, approve=False)

# 1. Upload the manuscript
upload_result = upload_document("../sample_data/draft_manuscript.html", SESSION_ID)
current_html = upload_result["html"]
print(f"Uploaded. {upload_result['chunks_count']} chunks.")

# 2. Read the flow diagram we rendered locally and base64-encode it
with open("../output/flow_diagram.png", "rb") as f:
    diagram_b64 = base64.b64encode(f.read()).decode("utf-8")

# 3. Ask the AI to insert it, with approval required before it takes effect
job_id = start_chat_async(
    message=(
        "Insert the attached flow diagram image immediately after the Methods "
        "section, before the Results section. Add a caption below it reading "
        "'Figure 1. PRISMA study flow diagram.' Do not alter any other section."
    ),
    session_id=SESSION_ID,
    document_html=current_html,
    approval_mode="ask_every_time",
    image_attachments=[
        {
            "id": "flow-diagram-1",
            "name": "flow_diagram.png",
            "base64Data": diagram_b64,
            "mimeType": "image/png",
            "size": len(diagram_b64),
        }
    ],
)
print(f"Job started: {job_id}")

# 4. Wait for it to reach awaiting_approval (or completed, or failed)
job = wait_for_job(job_id)
print(f"Job status: {job['status']}")

if job["status"] == "awaiting_approval":
    changes = get_pending_changes(job)
    print(f"\n{len(changes)} pending change(s):")
    for c in changes:
        print(json.dumps(c, indent=2))
        print("---")

    # Approve all proposed changes
    decisions = [{"change_id": c["change_id"], "approved": True} for c in changes]
    approve_result = approve_changes(SESSION_ID, job_id, decisions)
    print("Approve result:", json.dumps(approve_result, indent=2)[:500])

    from superdocs_client import export_and_verify

    output_path = export_and_verify(
        SESSION_ID,
        format="docx",
        output_path="../output/manuscript_with_diagram.docx",
        expect_image=True,
    )
    print(f"\nExported and verified: {output_path}")

elif job["status"] == "failed":
    print("Job failed:", job.get("error"))
elif job["status"] == "completed":
    print(
        "Completed without requiring approval — unexpected for ask_every_time, worth checking why."
    )
