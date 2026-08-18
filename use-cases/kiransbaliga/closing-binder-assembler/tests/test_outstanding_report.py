"""Tests for client-ready Outstanding Items Report generator."""

import os
import tempfile
import pytest

from exporter.outstanding_report import OutstandingReportGenerator
from matcher.semantic_matcher import SemanticMatcher
from parsers.checklist_parser import ChecklistParser
from parsers.document_parser import DocumentParser


def test_outstanding_report_generation():
    checklist_path = os.path.join(os.path.dirname(__file__), "..", "samples", "project_titan_checklist.json")
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "samples", "executed_documents")

    checklist = ChecklistParser().parse_file(checklist_path)
    doc_parser = DocumentParser()
    documents = []

    for f in sorted(os.listdir(docs_dir)):
        p = os.path.join(docs_dir, f)
        if os.path.isfile(p):
            documents.append(doc_parser.parse_file(p))

    matcher = SemanticMatcher()
    matches = matcher.match_pile(checklist, documents)
    docs_map = {d.doc_id: d for d in documents}

    with tempfile.TemporaryDirectory() as tmpdir:
        report_base = os.path.join(tmpdir, "Client_Outstanding_Report")
        reporter = OutstandingReportGenerator()
        res = reporter.generate_report(checklist, matches, docs_map, report_base)

        assert os.path.exists(res["pdf_path"])
        assert os.path.exists(res["md_path"])
        assert res["readiness_percentage"] > 0

        with open(res["md_path"], "r", encoding="utf-8") as f:
            md_text = f.read()

        assert "TRANSACTION OUTSTANDING ITEMS MEMORANDUM" in md_text
        assert "Closing Readiness Score" in md_text
        assert "Missing Deliverables" in md_text
