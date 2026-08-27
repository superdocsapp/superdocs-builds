import httpx

from superdocs_client import SuperDocsMutationAdapter


def test_mutation_adapter_calls_chat_approve_and_export() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/export"):
            return httpx.Response(200, json={"download_url": "https://example.test/file.docx"})
        return httpx.Response(200, json={"status": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SuperDocsMutationAdapter(
        "sk-test", "https://example.test", client)
    adapter.edit("session-1", "Fix the validated spelling diff.",
                 "ask_every_time")
    adapter.approve("session-1")
    result = adapter.export("session-1")

    assert result["download_url"].endswith("file.docx")
    assert [request.method for request in requests] == ["POST", "POST", "POST"]
    assert requests[0].url.path == "/v1/chat"
    assert requests[1].url.path == "/v1/chat/session-1/approve"
    assert requests[2].url.path == "/v1/documents/export"


def test_mutation_adapter_approve_sends_job_and_batch_changes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "completed"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SuperDocsMutationAdapter(
        "sk-test", "https://example.test", client)
    adapter.approve(
        "session-1",
        job_id="job-1",
        changes=[
            {"change_id": "change-1", "approved": True},
            {"change_id": "change-2", "approved": True},
        ],
    )

    assert requests[0].url.path == "/v1/chat/session-1/approve"
    assert requests[0].content == (
        b'{"approved":true,"job_id":"job-1","changes":'
        b'[{"change_id":"change-1","approved":true},'
        b'{"change_id":"change-2","approved":true}]}'
    )
