"""Deterministic end-to-end integration test proving the entire lifecycle and invariants."""

from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import (
    ChangeDecision,
    RunStatus,
    WikiDocument,
)
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter

CANONICAL_WIKI_CONTENT = """# Engineering Handbook

## Deployment

Production deployments happen every Friday.

## Database

Production uses PostgreSQL on AWS RDS.

## Incident Response

The on-call engineer must acknowledge incidents within 30 minutes.
"""


def test_deterministic_end_to_end_scenario():
    """End-to-End Scenario:

    1. Canonical wiki has Deployment, Database, Incident Response sections.
    2. Incoming decision: 'Production deployments are now daily. Incident acknowledgement SLA is now 15 minutes.'
    3. Agent uploads snapshot, queries SuperDocs chat, and extracts surgical changes.
    4. Human approval gate approves both changes.
    5. Agent applies surgical patches to Deployment and Incident Response.
    6. System strictly verifies: Database before == Database after (byte-for-byte).
    """
    # 1. Initialize host wiki
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-canonical",
            title="Engineering Handbook",
            content=CANONICAL_WIKI_CONTENT,
            content_version="1",
        )
    )

    # 2. SuperDocs mock handler simulating LLM chat response
    def superdocs_backend(action: str, params: dict):
        if action == "upload":
            assert params["title"] == "Engineering Handbook"
            return {"document_id": "sd_session_99"}
        if action == "chat":
            assert params["doc_id"] == "sd_session_99"
            return {
                "proposed_changes": [
                    {
                        "change_id": "prop_deploy",
                        "target_section": "Deployment",
                        "old_snippet": "Production deployments happen every Friday.",
                        "new_snippet": "Production deployments happen daily.",
                        "explanation": "Align deployment schedule with new daily cadence.",
                    },
                    {
                        "change_id": "prop_incident",
                        "target_section": "Incident Response",
                        "old_snippet": "The on-call engineer must acknowledge incidents within 30 minutes.",
                        "new_snippet": "The on-call engineer must acknowledge incidents within 15 minutes.",
                        "explanation": "Update on-call SLA to 15m.",
                    },
                ]
            }
        if action == "approve":
            return {"success": True}
        return {}

    superdocs = SuperDocsClient(mock_handler=superdocs_backend)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    decision_input = (
        "Starting August 18, production deployments will happen daily. "
        "Incident acknowledgement SLA is now 15 minutes."
    )

    # 3. Human Approval Gate
    def human_approver(doc: WikiDocument, proposed):
        assert len(proposed) == 2
        return [
            ChangeDecision(change_id="prop_deploy", approved=True),
            ChangeDecision(change_id="prop_incident", approved=True),
        ]

    # 4. Execute Agent run
    result = agent.run(
        doc_id="handbook-canonical",
        decision_text=decision_input,
        approval_gate=human_approver,
    )

    # 5. Verify results
    assert result.status == RunStatus.APPLIED
    assert len(result.applied_patches) == 2

    final_doc = wiki.fetch_page("handbook-canonical")
    assert final_doc.content_version == "3"  # 1 -> 2 (first patch) -> 3 (second patch)

    # Content assertions
    assert "Production deployments happen daily." in final_doc.content
    assert "The on-call engineer must acknowledge incidents within 15 minutes." in final_doc.content

    # INVARIANT CHECK: Database section is byte-for-byte identical
    before_sections = {s.title: s.content for s in DocumentPatcher.parse_sections(CANONICAL_WIKI_CONTENT)}
    after_sections = {s.title: s.content for s in final_doc.sections}

    assert before_sections["Database"] == after_sections["Database"] == "Production uses PostgreSQL on AWS RDS."
    assert before_sections["Deployment"] != after_sections["Deployment"]
    assert before_sections["Incident Response"] != after_sections["Incident Response"]

    assert DocumentPatcher.verify_untouched_invariant(
        CANONICAL_WIKI_CONTENT,
        final_doc.content,
        expected_modified_sections=["Deployment", "Incident Response"],
    )
