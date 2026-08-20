import asyncio

import pytest

from app.services.superdocs_workflow import SuperDocsWorkflow
from app.services.transmittal import build_transmittal_content
from app.superdocs.mock_client import MockSuperDocsClient


def test_transmittal_html_escapes_values_and_has_stable_chunks():
    kwargs = {
        "project": {
            "name": "Project <A>",
            "project_number": "P-1",
        },
        "submittal": {
            "number": "SUB-001",
            "title": "Flooring & Finish",
            "specification_section": "09 <90>",
        },
        "findings": [
            {
                "attribute": "Thickness",
                "requirement": ">= 3.0 mm",
                "submitted_value": "2.5 <mm>",
                "result": "DEVIATION",
                "specification_evidence": "Spec <page 2>",
                "submission_evidence": "Data & sheet",
                "status": "APPROVED",
                "reviewer_comment": "Needs clarification.",
            }
        ],
        "reviewer": "A & B",
    }

    first = build_transmittal_content(**kwargs)
    second = build_transmittal_content(**kwargs)

    assert first == second
    assert "Project &lt;A&gt;" in first
    assert "2.5 &lt;mm&gt;" in first
    assert "data-chunk-id=\"finding-1-review-comment\"" in first
    assert first.count("data-chunk-id=") == len(
        set(
            marker.split('"')[1]
            for marker in first.split("data-chunk-id=")[1:]
        )
    )


def test_mock_superdocs_complete_human_approval_lifecycle():
    async def scenario():
        client = MockSuperDocsClient()
        workflow = SuperDocsWorkflow(client)

        uploaded = await workflow.create_transmittal_document(
            "transmittal.html",
            "<html><body>Original</body></html>",
        )
        session_id = uploaded["session_id"]

        edit = await workflow.request_edit(
            session_id=session_id,
            html=uploaded["document_html"],
            message="Add a review note.",
        )
        assert edit["job_id"]
        assert edit["status"] == "processing"

        job = await workflow.get_job(edit["job_id"])
        assert job["status"] == "completed"
        assert job["proposed_changes"]

        change_id = job["proposed_changes"][0]["change_id"]
        approved = await workflow.approve(
            session_id=session_id,
            job_id=edit["job_id"],
            change_id=change_id,
            approved=True,
        )
        assert approved["approved"] is True

        exported = await workflow.export(
            session_id=session_id,
            format="docx",
            filename="transmittal.docx",
        )
        assert exported["format"] == "docx"
        assert exported["download_url"].endswith(".docx")

    asyncio.run(scenario())


def test_request_edit_rejects_missing_job_id():
    class MissingJobClient:
        async def edit_document(self, **kwargs):
            return {"status": "processing"}

    async def scenario():
        workflow = SuperDocsWorkflow(MissingJobClient())
        with pytest.raises(RuntimeError, match="job_id"):
            await workflow.request_edit(
                session_id="session",
                html="<p>html</p>",
                message="edit",
            )

    asyncio.run(scenario())


def test_mock_rejects_approval_before_job_is_ready():
    async def scenario():
        client = MockSuperDocsClient()
        uploaded = await client.upload_document(
            "transmittal.html",
            b"<html>Original</html>",
        )
        edit = await client.edit_document(
            uploaded["session_id"],
            "edit",
            uploaded["document_html"],
        )

        with pytest.raises(ValueError, match="not ready"):
            await client.approve_change(
                uploaded["session_id"],
                edit["job_id"],
                None,
                True,
            )

    asyncio.run(scenario())
