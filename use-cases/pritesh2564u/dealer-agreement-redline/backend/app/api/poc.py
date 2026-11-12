import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.superdocs.client import (
    SuperDocsClient,
    SuperDocsError,
)


router = APIRouter(
    prefix="/poc",
    tags=["poc"],
)


TEST_DATA = (
    Path(__file__).resolve().parents[3]
    / "test-data"
)


@router.post("/dealer-redline")
async def dealer_redline_poc():
    """
    End-to-end SuperDocs POC.

    Current flow:
        1. Upload dealer agreement as active document.
        2. Upload master agreement as attachment.
        3. Upload negotiation playbook as attachment.
        4. Ask SuperDocs to analyze the agreement.
        5. Return the raw chat response.

    We intentionally do not approve or export yet.
    First we inspect the exact proposed-change response.
    """

    dealer_file = (
        TEST_DATA / "dealer-agreement.docx"
    )

    master_file = (
        TEST_DATA / "master-agreement.docx"
    )

    playbook_file = (
        TEST_DATA / "negotiation-playbook.docx"
    )

    for file in (
        dealer_file,
        master_file,
        playbook_file,
    ):
        if not file.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Test file not found: {file}",
            )

    client = SuperDocsClient()

    session_id = str(uuid.uuid4())

    try:
        # --------------------------------------------------
        # 1. Upload dealer agreement as active document.
        # --------------------------------------------------

        dealer_document = (
            await client.upload_document(
                file_path=dealer_file,
                session_id=session_id,
            )
        )

        # --------------------------------------------------
        # 2. Upload master agreement as reference.
        # --------------------------------------------------

        master_attachment = (
            await client.upload_attachment(
                file_path=master_file,
                session_id=session_id,
            )
        )

        # --------------------------------------------------
        # 3. Upload negotiation playbook as reference.
        # --------------------------------------------------

        playbook_attachment = (
            await client.upload_attachment(
                file_path=playbook_file,
                session_id=session_id,
            )
        )

        # --------------------------------------------------
        # 4. Ask SuperDocs to analyze the dealer agreement.
        # --------------------------------------------------

        instruction = """
Compare the active dealer agreement against the approved
master agreement and evaluate all substantive deviations
using the negotiation playbook.

For every deviation:

1. Identify the agreement section.
2. Describe the substantive change.
3. Explain the difference between the master language
   and dealer language.
4. Determine whether the change is PRE-APPROVED,
   ESCALATE, or REFUSE according to the playbook.
5. Draft a concise counter-position.

Do not make any final changes to the document yet.

Return the proposed changes for human review.
""".strip()

        chat_response = await client.chat(
            session_id=session_id,
            message=instruction,
        )

        return {
            "session_id": session_id,
            "dealer_document": dealer_document,
            "master_attachment": master_attachment,
            "playbook_attachment": playbook_attachment,
            "chat_response": chat_response,
        }

    except SuperDocsError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        )