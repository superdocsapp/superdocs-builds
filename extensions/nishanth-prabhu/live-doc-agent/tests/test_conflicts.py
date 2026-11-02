"""Tests verifying optimistic concurrency conflict handling and human-gate race conditions."""

from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import ChangeDecision, RunStatus, WikiDocument
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter

SAMPLE_DOC = """# Engineering Handbook

## Deployment

Production deployments happen every Friday.
"""


def test_concurrent_edit_triggers_conflict_error():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    def mock_superdocs_handler(action: str, params: dict):
        if action == "upload":
            # Simulate another user editing the document right after it was uploaded
            doc = wiki.fetch_page("handbook-1")
            doc.content_version = "2"
            doc.content = SAMPLE_DOC.replace("Friday", "Thursday")
            wiki.seed_document(doc)
            return {"document_id": "sd_doc_1"}
        if action == "chat":
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
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs_handler)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(
        doc_id="handbook-1",
        decision_text="Daily deploys",
        auto_approve=True,
    )

    # Must detect optimistic concurrency conflict
    assert result.status == RunStatus.CONFLICT
    assert "conflict" in result.error_message.lower()
    assert len(result.applied_patches) == 0


def test_human_gate_race_condition_stale_proposal_aborts():
    """Prove the human-gate race condition:

    fetch -> propose -> human takes time -> external modification -> approve -> CONFLICT -> nothing committed.
    """
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    def mock_superdocs_handler(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_doc_1"}
        if action == "chat":
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
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs_handler)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    # During human deliberation time, an external modification happens!
    def human_approval_gate_with_external_race(doc, proposed):
        # External actor updates wiki while human is reviewing
        external_update = WikiDocument(
            doc_id="handbook-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC.replace("Friday", "every weekday"),
            content_version="2",
        )
        wiki.seed_document(external_update)

        # Human now approves the proposal
        return [ChangeDecision(change_id="c1", approved=True)]

    result = agent.run(
        doc_id="handbook-1",
        decision_text="Production deployments are now daily.",
        approval_gate=human_approval_gate_with_external_race,
    )

    # Conflict must be detected; nothing committed over the external edit
    assert result.status == RunStatus.CONFLICT
    assert len(result.applied_patches) == 0

    # Ensure external update was preserved and not clobbered
    current_wiki_doc = wiki.fetch_page("handbook-1")
    assert current_wiki_doc.content_version == "2"
    assert "every weekday" in current_wiki_doc.content
    assert "daily" not in current_wiki_doc.content
