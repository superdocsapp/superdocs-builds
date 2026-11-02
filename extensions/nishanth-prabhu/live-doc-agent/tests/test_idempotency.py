"""Tests verifying idempotency of decision synchronization."""

from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import RunStatus, WikiDocument
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter

SAMPLE_DOC = """# Engineering Handbook

## Deployment

Production deployments happen every Friday.
"""


def test_running_agent_twice_on_same_decision_is_idempotent():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    call_count = {"count": 0}

    def mock_superdocs_handler(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_doc_1"}
        if action == "chat":
            call_count["count"] += 1
            if call_count["count"] == 1:
                # 1st run: Propose update
                return {
                    "proposed_changes": [
                        {
                            "change_id": "c1",
                            "target_section": "Deployment",
                            "old_snippet": "Production deployments happen every Friday.",
                            "new_snippet": "Production deployments happen daily.",
                        }
                    ]
                }
            else:
                # 2nd run: Document already matches decision -> no-op
                return {"proposed_changes": []}
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs_handler)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    decision = "Deploy daily starting today."

    # Run 1
    res1 = agent.run(doc_id="handbook-1", decision_text=decision, auto_approve=True)
    assert res1.status == RunStatus.APPLIED
    assert len(res1.applied_patches) == 1

    doc_after_run1 = wiki.fetch_page("handbook-1")
    v1 = doc_after_run1.content_version

    # Run 2 with same decision
    res2 = agent.run(doc_id="handbook-1", decision_text=decision, auto_approve=True)
    assert res2.status == RunStatus.NOOP
    assert len(res2.applied_patches) == 0

    doc_after_run2 = wiki.fetch_page("handbook-1")
    # Content and version unchanged in run 2
    assert doc_after_run2.content == doc_after_run1.content
    assert doc_after_run2.content_version == v1
