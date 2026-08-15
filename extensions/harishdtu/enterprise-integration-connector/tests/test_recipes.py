import asyncio

import httpx
import pytest

from connector.callbacks import LoggingCallbackDispatcher
from connector.http_client import SuperDocsHTTPClient
from connector.worker import JobWorker
from schemas.common import ExportFormat
from schemas.generate_from_template import TemplateReference
from tests.conftest import json_response


@pytest.mark.asyncio
async def test_recipe_1_generate_contract_end_to_end(fake_server, client, fast_config):
    from recipes.recipe_1_generate_contract import GenerateContractRecipeInput, run_recipe_1

    fake_server.on("POST", "/v1/chat/async", lambda r: json_response(200, {
        "job_id": "job_1", "session_id": "s1", "status": "pending",
    }))
    fake_server.on("GET", "/v1/jobs/job_1", lambda r: json_response(200, {
        "job_id": "job_1", "status": "completed",
        "result": {"response": "Contract drafted", "document_changes": {"updated_html": "<p>contract</p>", "version_id": "v1"}},
    }))

    fast_client = SuperDocsHTTPClient(fast_config, transport=httpx.MockTransport(fake_server))
    worker = JobWorker(fast_config, fast_client)
    dispatcher = LoggingCallbackDispatcher()

    output = await run_recipe_1(fast_client, worker, GenerateContractRecipeInput(
        customer_name="Acme Corp",
        template_reference=TemplateReference(by_name="Standard NDA"),
        contract_details="Effective 2026-01-01, 12 month term.",
        callback_dispatcher=dispatcher,
    ))

    assert output.job_id == "job_1"
    assert output.status == "pending"  # returned immediately, non-blocking

    # Let the background worker actually finish and fire the callback.
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if tasks:
        await asyncio.wait(tasks, timeout=5)

    assert len(dispatcher.received) == 1
    assert dispatcher.received[0].status == "completed"


@pytest.mark.asyncio
async def test_recipe_2_edit_and_approve_end_to_end_item_level(fake_server, client, fast_config):
    from recipes.recipe_2_edit_and_approve import (
        EditAndAwaitReviewInput,
        ReviewDecision,
        SubmitReviewAndResumeInput,
        start_edit_and_await_review,
        submit_review_and_resume,
    )

    fake_server.on("POST", "/v1/chat/async", lambda r: json_response(200, {
        "job_id": "job_2", "session_id": "s2", "status": "pending",
    }))

    poll_state = {"phase": "awaiting"}

    def poll_handler(request):
        if poll_state["phase"] == "awaiting":
            return json_response(200, {
                "job_id": "job_2", "status": "awaiting_approval",
                "metadata": {"pending_changes": [
                    {"change_id": "c1", "operation": "edit", "chunk_id": "ch1", "old_html": "<p>a</p>", "new_html": "<p>b</p>"},
                    {"change_id": "c2", "operation": "edit", "chunk_id": "ch2", "old_html": "<p>x</p>", "new_html": "<p>y</p>"},
                ]},
            })
        return json_response(200, {"job_id": "job_2", "status": "completed", "result": {"response": "done"}})

    fake_server.on("GET", "/v1/jobs/job_2", poll_handler)

    fast_client = SuperDocsHTTPClient(fast_config, transport=httpx.MockTransport(fake_server))
    worker = JobWorker(fast_config, fast_client)
    dispatcher = LoggingCallbackDispatcher()

    # Phase A: start the edit, wait for the awaiting_approval callback.
    await start_edit_and_await_review(fast_client, worker, EditAndAwaitReviewInput(
        session_id="s2", instruction="Rewrite the liability clause", callback_dispatcher=dispatcher,
    ))
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.wait(tasks, timeout=5)

    assert dispatcher.received[-1].status == "awaiting_approval"
    pending = dispatcher.received[-1].poll_result.pending_changes
    assert {c.change_id for c in pending} == {"c1", "c2"}

    # Phase B: platform decides -- approve c1, reject c2 (item-level).
    approve_calls = {"n": 0}

    def approve_handler(request):
        approve_calls["n"] += 1
        import json
        body = json.loads(request.content)
        assert body["approved"] is True  # required top-level field
        decisions = {c["change_id"]: c["approved"] for c in body["changes"]}
        assert decisions == {"c1": True, "c2": False}
        return json_response(200, {"status": "in_progress"})

    fake_server.on("POST", "/v1/chat/s2/approve", approve_handler)
    poll_state["phase"] = "completed"

    await submit_review_and_resume(fast_client, worker, SubmitReviewAndResumeInput(
        session_id="s2", job_id="job_2",
        decisions=[ReviewDecision(change_id="c1", approved=True), ReviewDecision(change_id="c2", approved=False)],
        callback_dispatcher=dispatcher,
    ))
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    await asyncio.wait(tasks, timeout=5)

    assert approve_calls["n"] == 1
    assert dispatcher.received[-1].status == "completed"


@pytest.mark.asyncio
async def test_recipe_3_multi_format_export_continues_past_one_failure(fake_server, client):
    from recipes.recipe_3_approve_and_export import MultiFormatExportInput, run_recipe_3

    def docx_handler(request):
        return httpx.Response(200, content=b"docxbytes", headers={
            "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "Content-Disposition": 'attachment; filename="out.docx"',
        })

    def pdf_handler(request):
        # Simulate a real, non-retryable failure for this one format only.
        return json_response(422, {"detail": "PDF rendering failed: embedded font unsupported"})

    def md_handler(request):
        return httpx.Response(200, content=b"# markdown", headers={
            "Content-Type": "text/markdown", "Content-Disposition": 'attachment; filename="out.md"',
        })

    def route(request):
        import json
        body = json.loads(request.content)
        return {"docx": docx_handler, "pdf": pdf_handler, "markdown": md_handler}[body["format"]](request)

    fake_server.on("POST", "/v1/documents/export", route)

    output = await run_recipe_3(client, MultiFormatExportInput(
        session_id="s1", formats=[ExportFormat.docx, ExportFormat.pdf, ExportFormat.markdown],
    ))

    assert not output.all_succeeded
    assert output.succeeded_formats == [ExportFormat.docx, ExportFormat.markdown]
    pdf_result = next(r for r in output.results if r.format == ExportFormat.pdf)
    assert pdf_result.success is False
    assert pdf_result.error_type == "ValidationError"
    # The other two formats' artifacts are still present and usable despite the PDF failure.
    docx_result = next(r for r in output.results if r.format == ExportFormat.docx)
    assert docx_result.success is True
    assert docx_result.output.content_type.startswith("application/vnd.openxmlformats")
