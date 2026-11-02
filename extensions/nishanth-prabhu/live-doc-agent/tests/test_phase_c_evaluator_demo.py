"""Evaluator Demo Acceptance Test (Phase C / Phase D / Phase E)."""

from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import RunStatus, WikiDocument
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter

EVALUATOR_INITIAL_WIKI = """# Engineering Handbook

## Deployment

Deployments happen manually.

## Authentication

Use API keys.

## On-call

The team rotates weekly.
"""


def test_evaluator_demo_acceptance_scenario():
    """Phase C/D/E Core Acceptance Contract:

    Given:
      Engineering Handbook with Deployment, Authentication, and On-call.
    Decision:
      All deployments must now use the automated CI/CD pipeline.
    Expected:
      - Proposal updates only Deployment section.
      - Result status == APPLIED.
      - Authentication and On-call sections are byte-for-byte untouched.
    """
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-evaluator",
            title="Engineering Handbook",
            content=EVALUATOR_INITIAL_WIKI,
            content_version="1",
        )
    )

    def mock_superdocs(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_eval_doc"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c_deploy_eval",
                        "target_section": "Deployment",
                        "old_snippet": "Deployments happen manually.",
                        "new_snippet": "Deployments must use the automated CI/CD pipeline.",
                        "explanation": "Switch to automated CI/CD deployment pipeline.",
                        "confidence": 0.99,
                    }
                ]
            }
        if action == "approve":
            return {"success": True}
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    decision_text = "All deployments must now use the automated CI/CD pipeline."

    result = agent.run(
        doc_id="handbook-evaluator",
        decision_text=decision_text,
        auto_approve=True,
    )

    assert result.status == RunStatus.APPLIED
    assert len(result.applied_patches) == 1
    assert result.applied_patches[0].target_section == "Deployment"

    after_doc = wiki.fetch_page("handbook-evaluator")
    assert after_doc.content_version == "2"

    before_sections = {s.title: s.content for s in DocumentPatcher.parse_sections(EVALUATOR_INITIAL_WIKI)}
    after_sections = {s.title: s.content for s in after_doc.sections}

    # Verify modified section
    assert after_sections["Deployment"] == "Deployments must use the automated CI/CD pipeline."

    # Verify untouched sections
    assert before_sections["Authentication"] == after_sections["Authentication"] == "Use API keys."
    assert before_sections["On-call"] == after_sections["On-call"] == "The team rotates weekly."

    assert DocumentPatcher.verify_untouched_invariant(
        EVALUATOR_INITIAL_WIKI,
        after_doc.content,
        expected_modified_sections=["Deployment"],
    )
