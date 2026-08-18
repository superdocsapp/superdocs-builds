"""End-to-end integration test proving complete M&A closing binder assembly pipeline."""

import os
import tempfile
import pypdf
import pytest

from assembler.pdf_binder import PDFBinderAssembler
from exporter.folder_organizer import PerDocumentExporter
from exporter.outstanding_report import OutstandingReportGenerator
from matcher.semantic_matcher import SemanticMatcher
from parsers.checklist_parser import ChecklistParser
from parsers.document_parser import DocumentParser


def test_full_closing_binder_pipeline_end_to_end():
    checklist_path = os.path.join(os.path.dirname(__file__), "..", "samples", "project_titan_checklist.json")
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "samples", "executed_documents")

    checklist = ChecklistParser().parse_file(checklist_path)
    assert len(checklist.items) == 25

    doc_parser = DocumentParser()
    documents = []
    for f in sorted(os.listdir(docs_dir)):
        p = os.path.join(docs_dir, f)
        if os.path.isfile(p):
            meta = doc_parser.parse_file(p)
            documents.append(meta)

    assert len(documents) >= 20

    matcher = SemanticMatcher()
    matches = matcher.match_pile(checklist, documents)
    docs_map = {d.doc_id: d for d in documents}

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = os.path.join(tmpdir, "Closing_Binder_Final.pdf")
        assembler = PDFBinderAssembler(output_dir=tmpdir)
        final_pdf = assembler.assemble_binder(checklist, matches, docs_map, pdf_path)
        assert os.path.exists(final_pdf)

        reader = pypdf.PdfReader(final_pdf)
        assert len(reader.pages) > 25

        folder_dir = os.path.join(tmpdir, "Per_Document_Folder")
        exporter = PerDocumentExporter()
        folder_res = exporter.export_folder(checklist, matches, docs_map, folder_dir, create_zip=True)
        assert os.path.exists(folder_res["folder_path"])
        assert os.path.exists(folder_res["manifest_path"])
        assert os.path.exists(folder_res["index_path"])
        assert os.path.exists(folder_res["zip_path"])

        report_base = os.path.join(tmpdir, "Outstanding_Items_Report")
        reporter = OutstandingReportGenerator()
        rep_res = reporter.generate_report(checklist, matches, docs_map, report_base)
        assert os.path.exists(rep_res["pdf_path"])
        assert os.path.exists(rep_res["md_path"])
        assert rep_res["readiness_percentage"] > 0
