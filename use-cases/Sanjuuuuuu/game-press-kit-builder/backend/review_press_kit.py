import argparse
import json
from pathlib import Path

from backend.superdocs_client import SuperDocsClient
from backend.workflow import write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a rendered press kit with SuperDocs.")
    parser.add_argument("--upload-response", default="output/emberfall_upload_response.json")
    parser.add_argument("--output", default="output/emberfall_review_response.json")
    parser.add_argument("--checkpoint", default="output/emberfall_approval_checkpoint.json")
    args = parser.parse_args()

    upload_result = json.loads(Path(args.upload_response).read_text(encoding="utf-8"))
    session_id = upload_result["session_id"]
    document_html = upload_result["html"]

    message = """
Review this uploaded game press kit for publication readiness.

Preserve every source-backed fact exactly. Do not invent or alter facts, dates,
platforms, prices, awards, coverage, assets, or verbatim quotes.
Check that the three descriptions communicate the same game at increasing
levels of detail. Improve readability or formatting only when justified.
Return proposed changes with clear explanations and identifiers.
"""

    result = SuperDocsClient().chat(
        message=message,
        session_id=session_id,
        document_html=document_html,
    )
    write_json(Path(args.output), result)

    changes = result.get("document_changes", {})
    change_list = changes.get("changes", [])
    checkpoint = {
        "workflow": "game-press-kit",
        "workflow_status": "awaiting_human_approval" if change_list else "no_changes",
        "session_id": result.get("session_id", session_id),
        "job_id": result.get("job_id") or changes.get("job_id") or (change_list[0].get("job_id") if change_list else None),
        "requires_approval": bool(change_list),
        "changes": change_list,
        "original_html": document_html,
        "updated_html": changes.get("updated_html", document_html),
        "decisions": {},
    }
    write_json(Path(args.checkpoint), checkpoint)

    print(f"Review completed. Proposed changes: {len(change_list)}")
    print(f"Workflow status: {checkpoint['workflow_status']}")
    if change_list:
        print("Human approval is required before export.")
        print("Run: python backend\\approve_press_kit.py")


if __name__ == "__main__":
    main()
