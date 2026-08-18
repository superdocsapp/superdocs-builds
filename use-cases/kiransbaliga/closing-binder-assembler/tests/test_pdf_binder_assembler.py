"""Tests for hyperlinked PDF closing binder assembler."""

import os
import tempfile
import pypdf
import pytest

from assembler.pdf_binder import PDFBinderAssembler
from matcher.semantic_matcher import SemanticMatcher
from parsers.checklist_parser import ChecklistParser
from parsers.document_parser import DocumentParser


def test_pdf_binder_assembly_and_hyperlinks():
    checklist_path = os.path.join(os.path.dirname(__file__), "..", "samples", "project_titan_checklist.json")
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "samples", "executed_documents")

    checklist = ChecklistParser().parse_file(checklist_path)
    doc_parser = DocumentParser()
    documents = []

    for f in sorted(os.listdir(docs_dir))[:8]:
        p = os.path.join(docs_dir, f)
        if os.path.isfile(p):
            documents.append(doc_parser.parse_file(p))

    matcher = SemanticMatcher()
    matches = matcher.match_pile(checklist, documents)
    docs_map = {d.doc_id: d for d in documents}

    with tempfile.TemporaryDirectory() as tmpdir:
        output_pdf = os.path.join(tmpdir, "Test_Closing_Binder.pdf")
        assembler = PDFBinderAssembler(output_dir=tmpdir)
        final_pdf_path = assembler.assemble_binder(checklist, matches, docs_map, output_pdf)

        assert os.path.exists(final_pdf_path)
        assert os.path.getsize(final_pdf_path) > 1000

        reader = pypdf.PdfReader(final_pdf_path)
        assert len(reader.pages) > len(matches)

        assert reader.outline is not None
        assert len(reader.outline) > 0
