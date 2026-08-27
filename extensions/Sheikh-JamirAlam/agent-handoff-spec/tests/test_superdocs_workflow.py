from datetime import datetime, timezone

import httpx

from agents import DocumentState
from orchestrator import Orchestrator
from schema import ReviewState
from superdocs_client import SuperDocsFetchAdapter, SuperDocsMutationAdapter


def test_session_creation_and_failed_edit_are_explicit() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/sessions/init"):
            return httpx.Response(200, json={"session_id": "session-1"})
        if request.url.path == "/v1/chat":
            return httpx.Response(502, json={"error": "upstream failure"})
        return httpx.Response(200, json={"id": "doc-1", "html": "html", "review_state": "draft"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = SuperDocsFetchAdapter("sk-test", "https://example.test", client)
    mutation = SuperDocsMutationAdapter(
        "sk-test", "https://example.test", client)
    assert fetcher.create_session("doc-1") == "session-1"

    document = DocumentState("doc-1", ReviewState.DRAFT, {
        "narrative": "Payment recived.",
        "pricing_table": "1 x 10 = 10\nTotal: 10",
    })
    envelope = {
        "document_id": "doc-1", "assigned_to": "spelling-agent",
        "scope": {"action": "fix spelling", "target_sections": ["narrative"]},
        "review_state": "draft", "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }
    try:
        Orchestrator(mutation_adapter=mutation, session_id="session-1").run(
            document, envelope, {"narrative": {"recived": "received"}}
        )
    except httpx.HTTPStatusError as error:
        assert error.response.status_code == 502
    else:
        raise AssertionError("failed remote edit should stop the workflow")
    assert "/v1/chat" in paths


def test_complete_happy_path_refreshes_between_three_agent_actions() -> None:
    paths: list[str] = []
    fetch_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetch_count
        paths.append(request.url.path)
        if request.url.path.endswith("/sessions/init"):
            return httpx.Response(200, json={"session_id": "session-1"})
        if request.url.path == "/v1/documents/doc-1":
            fetch_count += 1
            return httpx.Response(200, json={"id": "doc-1", "html": str(fetch_count), "review_state": "draft" if fetch_count == 1 else "pending_review"})
        if request.url.path.endswith("/export"):
            return httpx.Response(200, json={"download_url": "signed"})
        return httpx.Response(200, json={"status": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = SuperDocsFetchAdapter("sk-test", "https://example.test", client)
    mutation = SuperDocsMutationAdapter(
        "sk-test", "https://example.test", client)
    document = DocumentState("doc-1", ReviewState.DRAFT, {
        "narrative": "Payment recived.",
        "pricing_table": "Widget: 2 x 25 = 50\nService: 3 x 20 = 60\nTotal: 100",
    })
    envelope = {
        "document_id": "doc-1", "assigned_to": "spelling-agent",
        "scope": {"action": "fix spelling", "target_sections": ["narrative"]},
        "review_state": "draft", "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }

    def extract(_: str) -> dict[str, str]:
        if fetch_count == 1:
            narrative = "Payment received."
            pricing = "Widget: 2 x 25 = 50\nService: 3 x 20 = 60\nTotal: 100"
        else:
            narrative = "Payment recived."
            pricing = "Widget: 2 x 25 = 50\nService: 3 x 20 = 60\nTotal: 110"
        return {"narrative": narrative, "pricing_table": pricing}

    result = Orchestrator(mutation_adapter=mutation, session_id="session-1",
                          document_fetcher=fetcher,
                          section_extractor=extract).run(
                              document, envelope, {"narrative": {"recived": "received"}})

    assert result.accepted is True
    assert len(result.validations) == 3
    assert paths.count("/v1/chat") == 3
    assert paths.count("/v1/documents/doc-1") == 2
    assert mutation.export("session-1")["download_url"] == "signed"
