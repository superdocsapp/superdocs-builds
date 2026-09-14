"""One-off, real-API verification for the human-in-the-loop revision path - the round's own stated
minimum contract (upload, chat, approve, export) requires approve_change/chat_with_approval to be
genuinely exercised, and this build never called either one before this fix. Run manually, once, with a
real SUPERDOCS_API_KEY, before committing/pushing.
"""

import os

from app.guide_generator import apply_guide_revision, generate_getting_started_guide, request_guide_revision
from app.superdocs_client import RealSuperDocsClient

api_key = os.environ.get("SUPERDOCS_API_KEY")
if not api_key:
    raise SystemExit("SUPERDOCS_API_KEY not set")

client = RealSuperDocsClient(api_key)

print("=== Step 1: generate a guide ===")
session_id = "verify-revision-1"
guide = generate_getting_started_guide(
    client,
    "Sign up for an account. Create an API key in Settings. Install the SDK with pip install widgets-sdk. "
    "Call client.create_widget to make your first widget.",
    session_id=session_id,
)
print(guide)
print()

print("=== Step 2: request a revision, inspect the real pending change ===")
job = request_guide_revision(client, session_id, "Add a troubleshooting section for authentication errors")
print("status:", job.status)
print("pending_changes:", len(job.pending_changes))
if job.pending_changes:
    change = job.pending_changes[0]
    print("ai_explanation:", repr(change.ai_explanation))
    print("old_html (truncated):", repr((change.old_html or "")[:200]))
    print("new_html (truncated):", repr((change.new_html or "")[:200]))
    print()

    print("=== Step 3: approve it, confirm the export reflects it ===")
    result = apply_guide_revision(client, session_id, job.job_id, change.change_id, approved=True)
    print(result)
    print()
    print("'troubleshooting' in result:", "troubleshoot" in result.lower())
else:
    print("ERROR: expected a pending change")

client.close()
