"""Tests verifying NOOP behavior when decisions do not impact the document."""

from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import RunStatus, WikiDocument
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter

SAMPLE_DOC = """# Engineering Handbook

## Deployment

Production deployments happen every Friday.
"""


def test_irrelevant_decision_results_in_noop():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    # SuperDocs detects no stale section
    def mock_superdocs_handler(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_doc_1"}
        if action == "chat":
            return {"proposed_changes": []}
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs_handler)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    decision_text = "The company holiday party will be on December 20th in the main lounge."

    result = agent.run(
        doc_id="handbook-1",
        decision_text=decision_text,
        auto_approve=True,
    )

    assert result.status == RunStatus.NOOP
    assert len(result.proposed_changes) == 0
    assert len(result.applied_patches) == 0

    doc_after = wiki.fetch_page("handbook-1")
    assert doc_after.content == SAMPLE_DOC
    assert doc_after.content_version == "1"
