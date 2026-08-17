from pathlib import Path
from uuid import uuid4

from superdocs.client import (
    SuperDocsClient,
)
from superdocs.polling import (
    wait_until_action_needed,
)


INPUT_PATH = Path(
    "outputs/scenario_a_reconciliation_memo.docx"
)

OUTPUT_PATH = Path(
    "outputs/scenario_a_reconciliation_memo_reviewed.docx"
)


EDIT_INSTRUCTION = """
Make exactly one surgical edit to this reconciliation memo:

Change the section heading "Executive Summary" to
"Reconciliation Summary".

Do not change any:
- extracted values
- classifications
- variance amounts
- file rules
- supporting evidence
- recommended actions
- disclaimer language

Do not add any new facts.
"""


def show_pending_changes(
    pending_changes: list[dict],
) -> None:
    print()
    print("=" * 70)
    print("PROPOSED CHANGES — HUMAN REVIEW")
    print("=" * 70)

    for index, change in enumerate(
        pending_changes,
        start=1,
    ):
        print()
        print(
            f"Change {index}"
        )

        print(
            "  change_id:",
            change.get("change_id"),
        )

        print(
            "  operation:",
            change.get("operation"),
        )

        print(
            "  explanation:",
            change.get("ai_explanation"),
        )

        print()
        print("  BEFORE")
        print("  ------")
        print(
            change.get("old_html")
        )

        print()
        print("  AFTER")
        print("  -----")
        print(
            change.get("new_html")
        )


def main() -> None:
    if not INPUT_PATH.exists():
        raise FileNotFoundError(
            (
                f"{INPUT_PATH} does not exist. "
                "Run python generate_outputs.py first."
            )
        )

    client = SuperDocsClient()

    session_id = (
        "scenario-a-memo-review-"
        + uuid4().hex[:8]
    )

    print(
        "SuperDocs human-review proof"
    )
    print("=" * 70)

    print(
        f"Session: {session_id}"
    )

    print()
    print(
        "1. Uploading generated memo..."
    )

    upload = client.upload_document(
        path=INPUT_PATH,
        session_id=session_id,
        open_mode="replace",
    )

    print(
        "   Uploaded:",
        upload.get("filename"),
    )

    print(
        "   document_id:",
        upload.get("document_id"),
    )

    print()
    print(
        "2. Sending edit instruction in Review Mode..."
    )

    started = client.start_async_chat(
        session_id=session_id,
        message=EDIT_INSTRUCTION,
        approval_mode="ask_every_time",
    )

    job_id = started.get(
        "job_id"
    )

    if not job_id:
        raise RuntimeError(
            (
                "SuperDocs did not return a job_id. "
                f"Response: {started}"
            )
        )

    print(
        f"   job_id: {job_id}"
    )

    while True:
        job = wait_until_action_needed(
            client=client,
            job_id=job_id,
        )

        status = job.get(
            "status"
        )

        if status == "completed":
            break

        metadata = (
            job.get("metadata")
            or {}
        )

        awaiting_kind = metadata.get(
            "awaiting_kind"
        )

        # Large edits use the same status but require
        # /continue rather than /approve.
        if awaiting_kind == "continue_prompt":
            prompt = (
                metadata.get(
                    "continue_prompt"
                )
                or {}
            )

            print()
            print(
                "SuperDocs paused a large operation:"
            )

            print(
                prompt.get(
                    "message",
                    "Continue?",
                )
            )

            choice = input(
                "Continue? [y/N]: "
            ).strip().lower()

            client.continue_job(
                session_id=session_id,
                job_id=job_id,
                should_continue=(
                    choice == "y"
                ),
            )

            continue

        pending_changes = (
            metadata.get(
                "pending_changes"
            )
            or []
        )

        if not pending_changes:
            raise RuntimeError(
                (
                    "Job is awaiting approval but "
                    "metadata.pending_changes is empty."
                )
            )

        show_pending_changes(
            pending_changes
        )

        print()
        decision = input(
            "Approve ALL proposed changes? [y/N]: "
        ).strip().lower()

        approve = (
            decision == "y"
        )

        decisions = [
            {
                "change_id": change[
                    "change_id"
                ],
                "approved": approve,
            }
            for change in pending_changes
        ]

        print()

        if approve:
            print(
                "Submitting human approval..."
            )
        else:
            print(
                "Submitting human rejection..."
            )

        client.approve_changes(
            session_id=session_id,
            job_id=job_id,
            approved=approve,
            changes=decisions,
        )

    result = (
        job.get("result")
        or {}
    )

    print()
    print("=" * 70)
    print("JOB COMPLETED")
    print("=" * 70)

    print(
        "SuperDocs response:"
    )

    print(
        result.get(
            "response",
            "(no response text)",
        )
    )

    document_changes = (
        result.get(
            "document_changes"
        )
        or {}
    )

    updated_html = (
        document_changes.get(
            "updated_html"
        )
    )

    if updated_html:
        print()
        print(
            "Updated HTML received:",
            len(updated_html),
            "characters",
        )

    print()
    print(
        "3. Exporting reviewed document..."
    )

    exported = client.export_document(
        session_id=session_id,
        output_path=OUTPUT_PATH,
        filename=(
            "scenario_a_reconciliation_memo_reviewed"
        ),
        file_format="docx",
    )

    print()
    print("=" * 70)
    print("END-TO-END SUCCESS")
    print("=" * 70)

    print(
        "Upload:   PASS"
    )

    print(
        "Edit:     PASS"
    )

    print(
        "Review:   PASS"
    )

    print(
        "Approve:  PASS"
    )

    print(
        "Export:   PASS"
    )

    print()

    print(
        f"Exported file: {exported.resolve()}"
    )


if __name__ == "__main__":
    main()