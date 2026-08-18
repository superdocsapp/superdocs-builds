"""Tests verifying defensive error boundaries for external infrastructure failures."""

from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import RunStatus, WikiDocument
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter


def test_wiki_fetch_failure_returns_error_result():
    # Empty wiki without requested document
    wiki = MemoryWikiAdapter()
    superdocs = SuperDocsClient()
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(doc_id="non-existent-doc-id", decision_text="Some decision")
    assert result.status == RunStatus.ERROR
    assert "failed to fetch wiki document" in result.error_message.lower()


def test_superdocs_upload_failure_returns_error_result():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="doc-1",
            title="Handbook",
            content="# Handbook\n\nContent",
            content_version="1",
        )
    )

    def failing_upload(action: str, params: dict):
        if action == "upload":
            raise RuntimeError("SuperDocs 503 Service Unavailable")
        return {}

    superdocs = SuperDocsClient(mock_handler=failing_upload)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(doc_id="doc-1", decision_text="Some decision")
    assert result.status == RunStatus.ERROR
    assert "superdocs interaction failed" in result.error_message.lower()
    assert "503" in result.error_message


def test_superdocs_chat_failure_returns_error_result():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="doc-1",
            title="Handbook",
            content="# Handbook\n\nContent",
            content_version="1",
        )
    )

    def failing_chat(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_doc_1"}
        if action == "chat":
            raise RuntimeError("LLM Context Window Exceeded")
        return {}

    superdocs = SuperDocsClient(mock_handler=failing_chat)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(doc_id="doc-1", decision_text="Some decision")
    assert result.status == RunStatus.ERROR
    assert "superdocs interaction failed" in result.error_message.lower()
    assert "context window" in result.error_message.lower()
