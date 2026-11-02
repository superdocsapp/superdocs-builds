"""Tests strictly proving byte-for-byte raw text preservation of unaffected sections."""

from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import RunStatus, WikiDocument
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter

COMPLEX_MARKDOWN = (
    "# Engineering Handbook\n\n"
    "## Deployment\n\n"
    "Deployments currently happen every Friday.\n\n"
    "## Complex Code Section\n\n"
    "```python\n"
    "def calculate_tax(amount: float) -> float:\n"
    "    # Note: 4 spaces indent, trailing spaces below   \n"
    "\treturn amount * 0.15\n"
    "```\n\n"
    "  - Item 1 with 2 spaces indent\n"
    "  - Item 2 with weird trailing space  \n\n"
    "## Authentication\n\n"
    "All requests require `Bearer <JWT_TOKEN>`.\n"
)


def test_byte_for_byte_preservation_of_complex_unaffected_sections():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="handbook-complex",
            title="Engineering Handbook",
            content=COMPLEX_MARKDOWN,
            content_version="1",
        )
    )

    def mock_superdocs(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_complex"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c_deploy",
                        "target_section": "Deployment",
                        "old_snippet": "Deployments currently happen every Friday.",
                        "new_snippet": "Deployments happen daily on CI.",
                        "explanation": "Update deployment cadence.",
                    }
                ]
            }
        if action == "approve":
            return {"success": True}
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(
        doc_id="handbook-complex",
        decision_text="Deploy daily",
        auto_approve=True,
    )

    assert result.status == RunStatus.APPLIED

    final_doc = wiki.fetch_page("handbook-complex")

    # Extract raw sections before and after
    before_sections = {s.title: s.raw_text for s in DocumentPatcher.parse_sections(COMPLEX_MARKDOWN)}
    after_sections = {s.title: s.raw_text for s in final_doc.sections}

    # Verify that Complex Code Section is BYTE-FOR-BYTE IDENTICAL
    assert before_sections["Complex Code Section"] == after_sections["Complex Code Section"]
    # Check that tabs, indentation, and trailing spaces in code block were preserved perfectly
    assert "\treturn amount * 0.15\n" in after_sections["Complex Code Section"]
    assert "# Note: 4 spaces indent, trailing spaces below   \n" in after_sections["Complex Code Section"]

    # Verify Authentication section is also byte-for-byte identical
    assert before_sections["Authentication"] == after_sections["Authentication"]

    # Verify only Deployment changed
    assert before_sections["Deployment"] != after_sections["Deployment"]
    assert "Deployments happen daily on CI." in after_sections["Deployment"]
