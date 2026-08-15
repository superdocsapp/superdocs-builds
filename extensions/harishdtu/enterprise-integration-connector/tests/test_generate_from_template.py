import base64
import json

import pytest

from connector.operations.generate_from_template import generate_from_template
from schemas.common import JobStatus
from schemas.generate_from_template import GenerateFromTemplateInput, TemplateReference
from tests.conftest import json_response


@pytest.mark.asyncio
async def test_by_name_reference_composes_instruction_and_uses_async_by_default(fake_server, client):
    fake_server.on("POST", "/v1/chat/async", lambda r: json_response(200, {
        "job_id": "job_1", "session_id": "s1", "status": "pending",
    }))

    result = await generate_from_template(client, GenerateFromTemplateInput(
        template_reference=TemplateReference(by_name="Standard NDA"),
        instruction="Draft an NDA for Acme Corp",
        session_id="s1",
    ))

    sent = fake_server.last_request_json()
    assert "Draft an NDA for Acme Corp" in sent["message"]
    assert "Standard NDA" in sent["message"]
    assert fake_server.requests[0].url.path == "/v1/chat/async"  # async by default
    assert result.job_id == "job_1"
    assert result.status == JobStatus.pending


@pytest.mark.asyncio
async def test_template_id_reference_composes_instruction(fake_server, client):
    fake_server.on("POST", "/v1/chat/async", lambda r: json_response(200, {
        "job_id": "job_2", "session_id": "s1", "status": "pending",
    }))

    await generate_from_template(client, GenerateFromTemplateInput(
        template_reference=TemplateReference(template_id="tmpl_123"),
        instruction="Generate the standard MSA",
        session_id="s1",
    ))

    sent = fake_server.last_request_json()
    assert "tmpl_123" in sent["message"]


@pytest.mark.asyncio
async def test_inline_base64_reference_uploads_then_generates(fake_server, client):
    upload_calls = {"n": 0}

    def upload_handler(request):
        upload_calls["n"] += 1
        body = json.loads(request.content)
        assert base64.b64decode(body["file_base64"]) == b"template bytes"
        return json_response(200, {"session_id": body["session_id"], "chunks_count": 2})

    def chat_handler(request):
        body = json.loads(request.content)
        # Session from the upload step must carry through to the chat call.
        assert body["session_id"]
        return json_response(200, {"job_id": "job_3", "session_id": body["session_id"], "status": "pending"})

    fake_server.on("POST", "/v1/documents/upload-base64", upload_handler)
    fake_server.on("POST", "/v1/chat/async", chat_handler)

    result = await generate_from_template(client, GenerateFromTemplateInput(
        template_reference=TemplateReference(
            inline_base64=base64.b64encode(b"template bytes").decode(), filename="template.docx",
        ),
        instruction="Fill in the customer name and date",
    ))

    assert upload_calls["n"] == 1
    assert result.job_id == "job_3"


@pytest.mark.asyncio
async def test_sync_path_returns_completed_status_immediately(fake_server, client):
    fake_server.on("POST", "/v1/chat", lambda r: json_response(200, {
        "session_id": "s1", "document_changes": {"updated_html": "<p>done</p>", "version_id": "v1"},
    }))

    result = await generate_from_template(client, GenerateFromTemplateInput(
        template_reference=TemplateReference(by_name="Invoice template"),
        instruction="Generate invoice #4021", session_id="s1", run_async=False,
    ))

    assert result.status == JobStatus.completed
    assert result.job_id is None
    assert result.updated_html == "<p>done</p>"


def test_template_reference_requires_exactly_one_shape():
    with pytest.raises(Exception, match="exactly one"):
        TemplateReference(template_id="a", by_name="b")
    with pytest.raises(Exception, match="exactly one"):
        TemplateReference()


def test_inline_base64_requires_filename():
    with pytest.raises(Exception, match="exactly one"):
        TemplateReference(inline_base64="abc==")  # no filename
