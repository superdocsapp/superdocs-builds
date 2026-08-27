import httpx

from schema import ReviewState
from superdocs_client import SuperDocsFetchAdapter


def test_fetch_adapter_gets_existing_document_without_uploading() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "id": "doc-123",
            "html": "<p>Existing document</p>",
            "review_state": "draft",
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = SuperDocsFetchAdapter(
        "sk-test", base_url="https://example.test", client=client)
    document = adapter.fetch("doc-123", lambda html: {"narrative": html})

    assert document.document_id == "doc-123"
    assert document.review_state is ReviewState.DRAFT
    assert document.sections == {"narrative": "<p>Existing document</p>"}
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v1/documents/doc-123"
    assert requests[0].url.params["include_html"] == "true"
    assert requests[0].headers["Authorization"] == "Bearer sk-test"
