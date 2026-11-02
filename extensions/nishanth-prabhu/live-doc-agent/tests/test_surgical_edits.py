"""Tests verifying surgical edits invariant: only stale paragraphs are edited."""

import pytest
from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import (
    ChangeDecision,
    RunStatus,
    WikiDocument,
)
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter

SAMPLE_DOC = """# Engineering Handbook

## Deployment

Production deployments happen every Friday.

## Database

Production uses PostgreSQL on AWS RDS.

## Incident Response

The on-call engineer must acknowledge incidents within 30 minutes.
"""


def test_surgical_edit_updates_only_stale_paragraphs():
    # Setup wiki with initial document
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    # Mock SuperDocs proposing changes for Deployment and Incident Response
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
                        "explanation": "Update deployment cadence to daily.",
                    },
                    {
                        "change_id": "c2",
                        "target_section": "Incident Response",
                        "old_snippet": "The on-call engineer must acknowledge incidents within 30 minutes.",
                        "new_snippet": "The on-call engineer must acknowledge incidents within 15 minutes.",
                        "explanation": "Update SLA to 15 minutes.",
                    },
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs_handler)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    decision_text = (
        "Starting August 18, production deployments will happen daily. "
        "Incident acknowledgement SLA is now 15 minutes."
    )

    # Human approves both
    def approval_gate(doc, proposed):
        return [ChangeDecision(change_id=p.change_id, approved=True) for p in proposed]

    result = agent.run(doc_id="handbook-1", decision_text=decision_text, approval_gate=approval_gate)

    assert result.status == RunStatus.APPLIED
    assert len(result.applied_patches) == 2

    # Check updated content
    updated_doc = wiki.fetch_page("handbook-1")
    assert "Production deployments happen daily." in updated_doc.content
    assert "The on-call engineer must acknowledge incidents within 15 minutes." in updated_doc.content

    # CRITICAL INVARIANT: Database section must be untouched!
    sections = {s.title: s.content for s in updated_doc.sections}
    assert sections["Database"] == "Production uses PostgreSQL on AWS RDS."

    # DocumentPatcher verification
    assert DocumentPatcher.verify_untouched_invariant(
        SAMPLE_DOC,
        updated_doc.content,
        expected_modified_sections=["Deployment", "Incident Response"],
    )


def test_partial_approval_applies_only_approved_section():
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
                    },
                    {
                        "change_id": "c2",
                        "target_section": "Incident Response",
                        "old_snippet": "The on-call engineer must acknowledge incidents within 30 minutes.",
                        "new_snippet": "The on-call engineer must acknowledge incidents within 5 minutes.",
                    },
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs_handler)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    # Approve Deployment (c1), reject Incident Response (c2)
    def approval_gate(doc, proposed):
        return [
            ChangeDecision(change_id="c1", approved=True),
            ChangeDecision(change_id="c2", approved=False, rejection_reason="5 min SLA too tight"),
        ]

    result = agent.run(
        doc_id="handbook-1",
        decision_text="Deploy daily and 5min SLA",
        approval_gate=approval_gate,
    )

    assert result.status == RunStatus.APPLIED
    assert len(result.applied_patches) == 1
    assert result.applied_patches[0].target_section == "Deployment"

    updated_doc = wiki.fetch_page("handbook-1")
    assert "Production deployments happen daily." in updated_doc.content
    # Incident Response remains old 30 minutes!
    assert "The on-call engineer must acknowledge incidents within 30 minutes." in updated_doc.content


def test_three_section_partial_approval_abc_pattern():
    """Test A -> Approve, B -> Reject, C -> Approve => A changed, B unchanged, C changed."""
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    # SuperDocs proposes changes for all three sections: Deployment (A), Database (B), Incident Response (C)
    def mock_superdocs_handler(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_doc_1"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "change_A",
                        "target_section": "Deployment",
                        "old_snippet": "Production deployments happen every Friday.",
                        "new_snippet": "Production deployments happen daily.",
                    },
                    {
                        "change_id": "change_B",
                        "target_section": "Database",
                        "old_snippet": "Production uses PostgreSQL on AWS RDS.",
                        "new_snippet": "Production uses CockroachDB on GCP.",
                    },
                    {
                        "change_id": "change_C",
                        "target_section": "Incident Response",
                        "old_snippet": "The on-call engineer must acknowledge incidents within 30 minutes.",
                        "new_snippet": "The on-call engineer must acknowledge incidents within 15 minutes.",
                    },
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs_handler)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    # Human Gate: A -> Approve, B -> Reject (migration postponed), C -> Approve
    def approval_gate(doc, proposed):
        return [
            ChangeDecision(change_id="change_A", approved=True),
            ChangeDecision(
                change_id="change_B",
                approved=False,
                rejection_reason="Database migration postponed to Q4",
            ),
            ChangeDecision(change_id="change_C", approved=True),
        ]

    result = agent.run(
        doc_id="handbook-1",
        decision_text="Update deployment cadence, database vendor, and on-call SLA",
        approval_gate=approval_gate,
    )

    assert result.status == RunStatus.APPLIED
    assert len(result.applied_patches) == 2
    applied_targets = [p.target_section for p in result.applied_patches]
    assert "Deployment" in applied_targets
    assert "Incident Response" in applied_targets
    assert "Database" not in applied_targets

    # Check updated content
    updated_doc = wiki.fetch_page("handbook-1")
    assert "Production deployments happen daily." in updated_doc.content
    assert "The on-call engineer must acknowledge incidents within 15 minutes." in updated_doc.content

    # Database MUST remain unchanged
    assert "Production uses PostgreSQL on AWS RDS." in updated_doc.content
    assert "CockroachDB" not in updated_doc.content

    # Strict invariant verification
    assert DocumentPatcher.verify_untouched_invariant(
        SAMPLE_DOC,
        updated_doc.content,
        expected_modified_sections=["Deployment", "Incident Response"],
    )
