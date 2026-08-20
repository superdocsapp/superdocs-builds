"""Keyless tests for SuperDocsClient -- the HTTP layer is mocked with
`responses`, but every mocked response shape here matches what the real API
actually returns, verified live against a real account while building a
different SuperDocs tool earlier in this project. These are not guessed
shapes.
"""

import responses

from battlecard.superdocs_client import SuperDocsClient, SuperDocsError

BASE = "https://api.superdocs.app"


@responses.activate
def test_upload_document_generates_and_sends_a_session_id():
    """The real API does not auto-generate a session_id -- omitting it means
    the upload never persists and no session_id comes back at all. The
    client must always generate and send one."""
    captured = {}

    def handler(request):
        import json
        body = json.loads(request.body)
        captured.update(body)
        return (200, {}, json.dumps({
            "html": None,
            "session_id": body["session_id"],
            "filename": body["filename"],
            "chunks_count": 5,
            "version_id": "v1",
            "persisted": True,
        }))

    responses.add_callback(
        responses.POST, f"{BASE}/v1/documents/upload-base64",
        callback=handler, content_type="application/json",
    )

    client = SuperDocsClient(api_key="sk_test")
    result = client.upload_document(file_bytes=b"fake docx bytes", filename="template.docx")

    assert captured["filename"] == "template.docx"
    assert captured["file_base64"]
    assert captured["session_id"]
    assert result.session_id == captured["session_id"]
    assert result.persisted is True


@responses.activate
def test_start_edit_posts_session_id_and_message():
    responses.add(
        responses.POST, f"{BASE}/v1/chat/async",
        json={"job_id": "job_123", "session_id": "sess_1", "status": "pending"},
        status=200,
    )
    client = SuperDocsClient(api_key="sk_test")
    result = client.start_edit(session_id="sess_1", instruction="fill in the sections")
    assert result.job_id == "job_123"
    assert result.status == "pending"


@responses.activate
def test_get_job_status_reads_document_changes_from_nested_result():
    """Real shape, verified live: document_changes is nested under
    result.document_changes, not top-level."""
    responses.add(
        responses.GET, f"{BASE}/v1/jobs/job_123",
        json={
            "status": "completed",
            "result": {
                "document_changes": {"updated_html": "<p>filled in</p>"},
            },
        },
        status=200,
    )
    client = SuperDocsClient(api_key="sk_test")
    result = client.get_job_status("job_123")
    assert result.status == "completed"
    assert result.updated_html == "<p>filled in</p>"


@responses.activate
def test_approve_sends_job_id_and_approval_flag():
    """job_id is required by the real API -- a bare {approved} 422s for real."""
    captured = {}

    def handler(request):
        import json
        captured.update(json.loads(request.body))
        return (200, {}, json.dumps({"status": "approved"}))

    responses.add_callback(
        responses.POST, f"{BASE}/v1/chat/sess_1/approve",
        callback=handler, content_type="application/json",
    )
    client = SuperDocsClient(api_key="sk_test")
    client.approve(session_id="sess_1", job_id="job_123", approved=True)
    assert captured == {"job_id": "job_123", "approved": True}


@responses.activate
def test_export_parses_filename_from_dual_form_content_disposition():
    """Real header carries both filename="..." and filename*=UTF-8''... on
    one line -- a naive split on 'filename=' picks up junk from the second
    form. Only the quoted value should be used."""
    responses.add(
        responses.POST, f"{BASE}/v1/documents/export",
        body=b"PK\x03\x04fakezip",
        status=200,
        headers={
            "content-disposition": 'attachment; filename="battlecard.docx"; filename*=UTF-8\'\'battlecard.docx',
            "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )
    client = SuperDocsClient(api_key="sk_test")
    result = client.export(session_id="sess_1", format="docx")
    assert result.filename == "battlecard.docx"
    assert result.file_bytes == b"PK\x03\x04fakezip"


@responses.activate
def test_non_2xx_response_raises_superdocs_error_with_status_and_body():
    responses.add(
        responses.POST, f"{BASE}/v1/chat/sess_1/approve",
        json={"detail": "Job is not awaiting approval (status: completed)"},
        status=400,
    )
    client = SuperDocsClient(api_key="sk_test")
    try:
        client.approve(session_id="sess_1", job_id="job_123", approved=True)
        assert False, "expected SuperDocsError"
    except SuperDocsError as exc:
        assert exc.status_code == 400
        assert "not awaiting approval" in exc.body
