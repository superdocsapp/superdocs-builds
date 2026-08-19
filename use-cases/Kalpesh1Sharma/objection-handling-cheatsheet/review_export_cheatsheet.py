from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from superdocs.client import (
    SuperDocsClient,
)
from superdocs.parser import (
    parse_pending_changes,
)
from superdocs.polling import (
    wait_until_action_needed,
)


INPUT_PATH = Path(
    "outputs/scenario_a_objection_cheatsheet.docx"
)

OUTPUT_PATH = Path(
    "outputs/"
    "scenario_a_objection_cheatsheet_reviewed.docx"
)


CHAT_QUESTION = """
Which objection in this cheatsheet has no response?

Answer only from this document.
Do not edit the document.
"""


EDIT_INSTRUCTION = """
Make exactly one surgical edit.

Change the document title:

"Objection Handling Cheatsheet"

to:

"Sales Objection Handling Cheatsheet"

Do not modify any objection text.
Do not modify any response text.
Do not fill in the missing response.
Do not add any new sales claims.
Do not remove any source references.
Do not make any other changes.
"""


def show_pending_changes(
    pending_changes: list[dict],
) -> None:
    print()
    print("=" * 70)
    print("PROPOSED CHANGES - HUMAN REVIEW")
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
            f"{INPUT_PATH} does not exist. "
            "Run python generate_outputs.py first."
        )

    client = SuperDocsClient()

    session_id = (
        "objection-review-"
        + uuid4().hex[:8]
    )

    print(
        "SuperDocs objection-cheatsheet proof"
    )
    print("=" * 70)

    print(
        f"Session: {session_id}"
    )

    # --------------------------------------------------
    # 1. Upload
    # --------------------------------------------------

    print()
    print(
        "1. Uploading generated cheatsheet..."
    )

    upload = client.upload_document(
        path=INPUT_PATH,
        session_id=session_id,
        open_mode="replace",
    )

    document_id = upload.get(
        "document_id"
    )

    print(
        "   Uploaded:",
        upload.get("filename"),
    )

    print(
        "   document_id:",
        document_id,
    )

    # --------------------------------------------------
    # 2. Read-only Chat
    # --------------------------------------------------

    print()
    print(
        "2. Asking grounded read-only question..."
    )

    chat_result = client.chat(
        session_id=session_id,
        document_id=document_id,
        message=CHAT_QUESTION,
    )

    chat_text = (
        chat_result.get("response")
        or chat_result.get("message")
        or str(chat_result)
    )

    print()
    print(
        "CHAT RESPONSE:"
    )
    print(
        chat_text
    )

    # --------------------------------------------------
    # 3. Review edit
    # --------------------------------------------------

    print()
    print(
        "3. Sending surgical edit "
        "in Review Mode..."
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
            "SuperDocs did not return a job_id. "
            f"Response: {started}"
        )

    print(
        f"   job_id: {job_id}"
    )

    # --------------------------------------------------
    # 4. Human gate
    # --------------------------------------------------

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

        if awaiting_kind == "continue_prompt":
            prompt = (
                metadata.get(
                    "continue_prompt"
                )
                or {}
            )

            print()
            print(
                prompt.get(
                    "message",
                    "Continue operation?",
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
            parse_pending_changes(
                metadata.get(
                    "pending_changes"
                )
            )
        )

        if not pending_changes:
            raise RuntimeError(
                "Job is awaiting approval, "
                "but no proposed changes "
                "were returned."
            )

        show_pending_changes(
            pending_changes
        )

        print()
        decision = input(
            "Approve ALL proposed changes? "
            "[y/N]: "
        ).strip().lower()

        approve = (
            decision == "y"
        )

        decisions = [
            {
                "change_id":
                    change["change_id"],

                "approved":
                    approve,
            }
            for change in pending_changes
        ]

        client.approve_changes(
            session_id=session_id,
            job_id=job_id,
            approved=approve,
            changes=decisions,
        )

        print()

        if approve:
            print(
                "Human approval submitted."
            )
        else:
            print(
                "Human rejection submitted."
            )

    # --------------------------------------------------
    # 5. Export
    # --------------------------------------------------

    print()
    print(
        "5. Exporting reviewed document..."
    )

    exported = client.export_document(
        session_id=session_id,
        output_path=OUTPUT_PATH,
        filename=(
            "scenario_a_objection_"
            "cheatsheet_reviewed"
        ),
        file_format="docx",
    )

    print()
    print("=" * 70)
    print("END-TO-END SUCCESS")
    print("=" * 70)

    print("Upload:   PASS")
    print("Chat:     PASS")
    print("Review:   PASS")

    if approve:
        print("Approve:  PASS")
    else:
        print("Reject:   PASS")

    print("Export:   PASS")

    print()
    print(
        f"Exported file: "
        f"{exported.resolve()}"
    )


if __name__ == "__main__":
    main()