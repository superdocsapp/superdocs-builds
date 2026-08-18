import argparse
import json
from pathlib import Path

from backend.superdocs_client import SuperDocsClient
from backend.workflow import apply_local_decisions, read_json, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Human gate for proposed SuperDocs changes.")
    parser.add_argument("--checkpoint", default="output/emberfall_approval_checkpoint.json")
    parser.add_argument("--yes", action="store_true", help="Approve every proposed change without prompting.")
    parser.add_argument("--no-api", action="store_true", help="Record the human decision locally without calling SuperDocs approve.")
    args = parser.parse_args()

    checkpoint_path = Path(args.checkpoint)
    checkpoint = read_json(checkpoint_path)
    changes = checkpoint.get("changes", [])

    if checkpoint.get("workflow_status") == "approved":
        print("Approval checkpoint is already approved.")
        return

    decisions: dict[str, str] = {}
    for change in changes:
        cid = change.get("change_id")
        if not cid:
            continue
        if args.yes:
            answer = "y"
        else:
            print("\nProposed change:")
            print(f"  ID: {cid}")
            print(f"  Operation: {change.get('operation')}")
            print(f"  Explanation: {change.get('ai_explanation')}")
            answer = input("Approve this change? [y/N]: ").strip().lower()
        decisions[cid] = "approve" if answer == "y" else "reject"

    # If the API supplied a job/change identifier, mirror the explicit human
    # decision to the API as well. Rejections do not discard other changes.
    if not args.no_api and checkpoint.get("session_id"):
        client = SuperDocsClient()
        for change in changes:
            cid = change.get("change_id")
            decision = decisions.get(cid)
            if not cid or decision is None:
                continue
            job_id = change.get("job_id") or checkpoint.get("job_id")
            if not job_id:
                continue
            client.approve(
                session_id=checkpoint["session_id"],
                job_id=job_id,
                approved=decision == "approve",
                change_id=cid,
                feedback="Human gate decision: " + decision,
                changes=[change],
            )

    checkpoint = apply_local_decisions(checkpoint, decisions)
    write_json(checkpoint_path, checkpoint)
    print(f"Saved human approval decisions to {checkpoint_path}")
    print(f"Approved: {sum(v == 'approve' for v in decisions.values())}")
    print(f"Rejected: {sum(v == 'reject' for v in decisions.values())}")


if __name__ == "__main__":
    main()
