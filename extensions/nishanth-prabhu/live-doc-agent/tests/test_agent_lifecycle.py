"""Tests verifying complete agent lifecycle flows and the Phase B acceptance test."""

from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import (
    ChangeDecision,
    RunStatus,
    WikiDocument,
)
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter


def test_default_gate_rejects_without_auto_approve():
    doc_content = "# Handbook\n\n## Section A\n\nOld content."
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(doc_id="doc-1", title="Handbook", content=doc_content, content_version="1")
    )

    def mock_sd(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_1"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c1",
                        "target_section": "Section A",
                        "old_snippet": "Old content.",
                        "new_snippet": "New content.",
                    }
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_sd)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    # No approval gate provided and auto_approve is False
    result = agent.run(doc_id="doc-1", decision_text="Update section A", auto_approve=False)
    assert result.status == RunStatus.REJECTED
    assert len(result.applied_patches) == 0

    # Content unchanged
    assert wiki.fetch_page("doc-1").content == doc_content


def test_approval_gate_exception_returns_error_result():
    """Verify that exceptions thrown inside human approval callback are caught cleanly."""
    doc_content = "# Handbook\n\n## Section A\n\nOld content."
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(doc_id="doc-1", title="Handbook", content=doc_content, content_version="1")
    )

    def mock_sd(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_1"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c1",
                        "target_section": "Section A",
                        "old_snippet": "Old content.",
                        "new_snippet": "New content.",
                    }
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_sd)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    def crashing_gate(doc, proposed):
        raise RuntimeError("UI Modal Terminated Unexpectedly")

    result = agent.run(doc_id="doc-1", decision_text="Update section A", approval_gate=crashing_gate)
    assert result.status == RunStatus.ERROR
    assert "approval gate failed" in result.error_message.lower()
    assert "ui modal terminated" in result.error_message.lower()
    assert len(result.applied_patches) == 0


def test_user_override_text_applies_custom_user_snippet():
    doc_content = "# Handbook\n\n## Cadence\n\nReleases happen monthly."
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(doc_id="doc-1", title="Handbook", content=doc_content, content_version="1")
    )

    def mock_sd(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_1"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c1",
                        "target_section": "Cadence",
                        "old_snippet": "Releases happen monthly.",
                        "new_snippet": "Releases happen daily.",
                    }
                ]
            }
        if action == "approve":
            return {"success": True}
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_sd)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    # Reviewer modifies replacement text from "daily" to "bi-weekly on Tuesdays"
    def custom_approval_gate(doc, proposed):
        return [
            ChangeDecision(
                change_id="c1",
                approved=True,
                user_override_text="Releases happen bi-weekly on Tuesdays.",
            )
        ]

    result = agent.run(
        doc_id="doc-1",
        decision_text="Release cadence changes",
        approval_gate=custom_approval_gate,
    )

    assert result.status == RunStatus.APPLIED
    assert len(result.applied_patches) == 1
    assert result.applied_patches[0].replacement_snippet == "Releases happen bi-weekly on Tuesdays."

    updated_doc = wiki.fetch_page("doc-1")
    assert "Releases happen bi-weekly on Tuesdays." in updated_doc.content
    assert "Releases happen daily." not in updated_doc.content


def test_phase_b_acceptance_scenario():
    """Phase B Acceptance Test:

    Given:
      Engineering Handbook with Deployment, Incident Response, Security
    Decision:
      Deployments no longer require manual approval. They may be deployed automatically after CI passes.
    SuperDocs Proposal:
      Target: Deployment
      old_snippet: Deployments currently require manual approval.
      new_snippet: Deployments may be deployed automatically after CI passes.
    Human:
      Approves
    Assert:
      result.status == APPLIED
      incident_response_before == incident_response_after
      security_before == security_after
      len(result.applied_patches) == 1
    """
    initial_handbook = """# Engineering Handbook

## Deployment

Deployments currently require manual approval.

## Incident Response

Create an incident channel immediately.

## Security

All production access requires MFA.
"""
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-prod",
            title="Engineering Handbook",
            content=initial_handbook,
            content_version="1",
        )
    )

    def mock_superdocs(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_acceptance_doc"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "deployment-policy",
                        "target_section": "Deployment",
                        "old_snippet": "Deployments currently require manual approval.",
                        "new_snippet": "Deployments may be deployed automatically after CI passes.",
                        "explanation": "The deployment policy has changed.",
                        "confidence": 0.98,
                    }
                ]
            }
        if action == "approve":
            assert params["change_ids"] == ["deployment-policy"]
            return {"success": True}
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    decision = (
        "Deployments no longer require manual approval. "
        "They may be deployed automatically after CI passes."
    )

    def human_approver(doc, proposed):
        assert len(proposed) == 1
        assert proposed[0].change_id == "deployment-policy"
        return [ChangeDecision(change_id="deployment-policy", approved=True)]

    result = agent.run(
        doc_id="handbook-prod",
        decision_text=decision,
        approval_gate=human_approver,
    )

    assert result.status == RunStatus.APPLIED
    assert len(result.applied_patches) == 1

    final_doc = wiki.fetch_page("handbook-prod")

    # Invariant checks
    before_sections = {s.title: s.content for s in DocumentPatcher.parse_sections(initial_handbook)}
    after_sections = {s.title: s.content for s in final_doc.sections}

    assert before_sections["Incident Response"] == after_sections["Incident Response"] == "Create an incident channel immediately."
    assert before_sections["Security"] == after_sections["Security"] == "All production access requires MFA."
    assert after_sections["Deployment"] == "Deployments may be deployed automatically after CI passes."

    assert DocumentPatcher.verify_untouched_invariant(
        initial_handbook,
        final_doc.content,
        expected_modified_sections=["Deployment"],
    )
