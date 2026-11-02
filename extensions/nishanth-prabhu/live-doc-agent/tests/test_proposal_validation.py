"""Tests verifying pre-approval proposal validation and whitespace edge cases."""

import pytest
from live_doc_agent.agent import LiveDocAgent
from live_doc_agent.models import (
    Patch,
    ProposedChange,
    RunStatus,
    WikiDocument,
)
from live_doc_agent.patcher import DocumentPatcher
from live_doc_agent.superdocs.client import SuperDocsClient
from live_doc_agent.wiki.memory import MemoryWikiAdapter

SAMPLE_DOC = """# Engineering Handbook

## Deployment

Deployments currently require manual approval from team leads.

## Database

Production uses PostgreSQL on AWS RDS.
"""


def test_invalid_target_section_yields_validation_failed():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="doc-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    def mock_superdocs(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_1"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c1",
                        "target_section": "NonExistentSection",
                        "old_snippet": "foo",
                        "new_snippet": "bar",
                    }
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(doc_id="doc-1", decision_text="Some decision", auto_approve=True)
    assert result.status == RunStatus.VALIDATION_FAILED
    assert "not found" in result.error_message.lower()


def test_missing_old_snippet_yields_validation_failed():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="doc-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    def mock_superdocs(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_1"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c1",
                        "target_section": "Deployment",
                        "old_snippet": "This text does not exist anywhere in the section.",
                        "new_snippet": "New replacement",
                    }
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(doc_id="doc-1", decision_text="Some decision", auto_approve=True)
    assert result.status == RunStatus.VALIDATION_FAILED
    assert "not found" in result.error_message.lower()


def test_ambiguous_old_snippet_yields_validation_failed():
    ambiguous_doc = """# Handbook

## Guidelines

Always follow the standard rules.
Always follow the standard rules.
"""
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="doc-ambig",
            title="Handbook",
            content=ambiguous_doc,
            content_version="1",
        )
    )

    def mock_superdocs(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_1"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "c1",
                        "target_section": "Guidelines",
                        "old_snippet": "Always follow the standard rules.",
                        "new_snippet": "Follow updated rules.",
                    }
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(doc_id="doc-ambig", decision_text="Some decision", auto_approve=True)
    assert result.status == RunStatus.VALIDATION_FAILED
    assert "ambiguous" in result.error_message.lower()


def test_duplicate_change_ids_yields_validation_failed():
    wiki = MemoryWikiAdapter()
    wiki.seed_document(
        WikiDocument(
            doc_id="doc-1",
            title="Engineering Handbook",
            content=SAMPLE_DOC,
            content_version="1",
        )
    )

    def mock_superdocs(action: str, params: dict):
        if action == "upload":
            return {"document_id": "sd_1"}
        if action == "chat":
            return {
                "proposed_changes": [
                    {
                        "change_id": "dup_id",
                        "target_section": "Deployment",
                        "old_snippet": "Deployments currently require manual approval from team leads.",
                        "new_snippet": "Daily deploys.",
                    },
                    {
                        "change_id": "dup_id",  # Duplicate ID!
                        "target_section": "Database",
                        "old_snippet": "Production uses PostgreSQL on AWS RDS.",
                        "new_snippet": "Production uses MySQL.",
                    },
                ]
            }
        return {}

    superdocs = SuperDocsClient(mock_handler=mock_superdocs)
    agent = LiveDocAgent(wiki_adapter=wiki, superdocs_client=superdocs)

    result = agent.run(doc_id="doc-1", decision_text="Some decision", auto_approve=True)
    assert result.status == RunStatus.VALIDATION_FAILED
    assert "duplicate change ids" in result.error_message.lower()


def test_invalid_confidence_yields_validation_failed():
    doc = WikiDocument(
        doc_id="doc-1",
        title="Engineering Handbook",
        content=SAMPLE_DOC,
        content_version="1",
    )
    change = ProposedChange(
        change_id="c1",
        target_section="Deployment",
        old_snippet="Deployments currently require manual approval from team leads.",
        new_snippet="Daily deploys.",
        confidence=1.5,  # Invalid: > 1.0
    )

    with pytest.raises(Exception) as exc:
        DocumentPatcher.validate_proposal(doc, change)
    assert "confidence" in str(exc.value).lower()


def test_whitespace_normalized_patch_replacement():
    """Verify that multi-line or whitespace-varied target snippets match cleanly."""
    doc_with_multiline_whitespace = """# Engineering Handbook

## Deployment

Deployments   currently   require
manual approval  from  team leads.

## Database

Production uses PostgreSQL.
"""
    patch = Patch(
        patch_id="p1",
        target_section="Deployment",
        original_snippet="Deployments currently require manual approval from team leads.",
        replacement_snippet="Deployments are automated on CI.",
        expected_version="1",
    )

    patched_content = DocumentPatcher.apply_patch_to_content(
        doc_with_multiline_whitespace, patch
    )
    assert "Deployments are automated on CI." in patched_content
    assert "Production uses PostgreSQL." in patched_content
    assert "manual approval" not in patched_content
