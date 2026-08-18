"""Tests for semantic document-to-checklist matching over messy/inconsistent filenames."""

import os
import pytest

from core.enums import ExecutionStatus, MatchConfidence
from matcher.semantic_matcher import SemanticMatcher
from parsers.checklist_parser import ChecklistParser
from parsers.document_parser import DocumentParser


@pytest.fixture
def test_setup():
    checklist_path = os.path.join(os.path.dirname(__file__), "..", "samples", "project_titan_checklist.json")
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "samples", "executed_documents")

    checklist = ChecklistParser().parse_file(checklist_path)
    doc_parser = DocumentParser()
    documents = []

    for f in sorted(os.listdir(docs_dir)):
        if f.startswith("."):
            continue
        p = os.path.join(docs_dir, f)
        if os.path.isfile(p):
            documents.append(doc_parser.parse_file(p))

    return checklist, documents


def test_semantic_matcher_survives_messy_filenames(test_setup):
    checklist, documents = test_setup
    matcher = SemanticMatcher()
    matches = matcher.match_pile(checklist, documents)

    assert len(matches) == len(checklist.items)

    m_merger = next(m for m in matches if m.tab_number == 1)
    assert m_merger.confidence in [MatchConfidence.HIGH, MatchConfidence.MEDIUM]
    assert "signed" in m_merger.matched_filename.lower()
    assert m_merger.execution_status == ExecutionStatus.FULLY_EXECUTED

    m_gs = next(m for m in matches if m.tab_number == 12)
    assert m_gs.confidence in [MatchConfidence.HIGH, MatchConfidence.MEDIUM]
    assert m_gs.matched_filename == "scan_00192.pdf"
    assert m_gs.execution_status == ExecutionStatus.NON_SIGNATURE_DOC

    m_escrow = next(m for m in matches if m.tab_number == 2)
    assert m_escrow.confidence in [MatchConfidence.HIGH, MatchConfidence.MEDIUM]
    assert m_escrow.matched_filename == "agmt_clean_v2.docx"
    assert m_escrow.execution_status == ExecutionStatus.UNSIGNED_DRAFT

    m_voting = next(m for m in matches if m.tab_number == 4)
    assert m_voting.matched_filename == "Titan_Voting_Agmt_partial.pdf"
    assert m_voting.execution_status == ExecutionStatus.PARTIALLY_EXECUTED

    missing_matches = [m for m in matches if m.execution_status == ExecutionStatus.MISSING]
    assert len(missing_matches) > 0
