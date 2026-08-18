"""Model Context Protocol (MCP) server exposing M&A Closing-Binder Assembler tools."""

import json
import os
from typing import Any, Dict, List, Optional

from assembler.pdf_binder import PDFBinderAssembler
from core.models import ClosingChecklist, DocumentMetadata, MatchResult
from exporter.folder_organizer import PerDocumentExporter
from exporter.outstanding_report import OutstandingReportGenerator
from matcher.semantic_matcher import SemanticMatcher
from parsers.checklist_parser import ChecklistParser
from parsers.document_parser import DocumentParser


class ClosingBinderMCPServer:
    """Exposes M&A Closing-Binder tools to MCP clients (Claude, Cursor, AI agents)."""

    def __init__(self):
        self.checklist_parser = ChecklistParser()
        self.doc_parser = DocumentParser()
        self.matcher = SemanticMatcher()
        self.assembler = PDFBinderAssembler()
        self.exporter = PerDocumentExporter()
        self.reporter = OutstandingReportGenerator()

    def list_tools(self) -> List[Dict[str, Any]]:
        """Returns tool schema definitions adhering to Model Context Protocol."""
        return [
            {
                "name": "assemble_closing_binder",
                "description": "Assembles a multi-document M&A closing checklist and file bundle into a navigable hyperlinked PDF binder, per-document folder, and client-ready outstanding items report.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "checklist_path": {"type": "string", "description": "Path to closing checklist (JSON/MD/CSV)"},
                        "documents_dir": {"type": "string", "description": "Directory containing executed transaction files"},
                        "output_dir": {"type": "string", "description": "Directory where outputs will be saved"},
                        "deal_name": {"type": "string", "description": "Optional custom deal title"},
                    },
                    "required": ["checklist_path", "documents_dir", "output_dir"],
                },
            },
            {
                "name": "match_documents_to_checklist",
                "description": "Semantically matches executed documents in a directory to closing checklist lines by content rather than filename.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "checklist_path": {"type": "string", "description": "Path to closing checklist"},
                        "documents_dir": {"type": "string", "description": "Directory containing transaction documents"},
                    },
                    "required": ["checklist_path", "documents_dir"],
                },
            },
            {
                "name": "detect_unsigned_documents",
                "description": "Scans documents in a folder and detects unsigned drafts, blank signature lines ('By: _____'), and missing counterparty execution.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "documents_dir": {"type": "string", "description": "Directory containing files to audit"},
                    },
                    "required": ["documents_dir"],
                },
            },
            {
                "name": "generate_outstanding_items_report",
                "description": "Generates a client-ready memorandum of missing deliverables and incomplete signatures that counsel can email directly to clients.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "checklist_path": {"type": "string", "description": "Path to closing checklist"},
                        "documents_dir": {"type": "string", "description": "Directory containing files"},
                        "output_path": {"type": "string", "description": "Destination path for report without extension"},
                    },
                    "required": ["checklist_path", "documents_dir", "output_path"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the requested tool by name."""
        if name == "assemble_closing_binder":
            return self._tool_assemble(
                checklist_path=arguments["checklist_path"],
                documents_dir=arguments["documents_dir"],
                output_dir=arguments["output_dir"],
                deal_name=arguments.get("deal_name"),
            )
        elif name == "match_documents_to_checklist":
            return self._tool_match(
                checklist_path=arguments["checklist_path"],
                documents_dir=arguments["documents_dir"],
            )
        elif name == "detect_unsigned_documents":
            return self._tool_detect_unsigned(
                documents_dir=arguments["documents_dir"],
            )
        elif name == "generate_outstanding_items_report":
            return self._tool_generate_report(
                checklist_path=arguments["checklist_path"],
                documents_dir=arguments["documents_dir"],
                output_path=arguments["output_path"],
            )
        else:
            raise ValueError(f"Unknown MCP tool: {name}")

    def _tool_assemble(self, checklist_path: str, documents_dir: str, output_dir: str, deal_name: Optional[str]) -> Dict[str, Any]:
        checklist = self.checklist_parser.parse_file(checklist_path)
        docs = self._load_documents_from_dir(documents_dir)
        docs_map = {d.doc_id: d for d in docs}
        matches = self.matcher.match_pile(checklist, docs)

        os.makedirs(output_dir, exist_ok=True)
        pdf_path = os.path.join(output_dir, "Closing_Binder_Combined.pdf")
        self.assembler.assemble_binder(checklist, matches, docs_map, pdf_path, deal_name)

        folder_dir = os.path.join(output_dir, "Per_Document_Folder")
        folder_res = self.exporter.export_folder(checklist, matches, docs_map, folder_dir, create_zip=True)

        report_base = os.path.join(output_dir, "Outstanding_Items_Report")
        rep_res = self.reporter.generate_report(checklist, matches, docs_map, report_base)

        return {
            "status": "SUCCESS",
            "deal_name": checklist.deal_name,
            "total_items": len(checklist.items),
            "readiness_percentage": rep_res["readiness_percentage"],
            "pdf_binder_path": pdf_path,
            "per_document_folder": folder_res["folder_path"],
            "per_document_zip": folder_res["zip_path"],
            "outstanding_report_pdf": rep_res["pdf_path"],
            "outstanding_report_md": rep_res["md_path"],
        }

    def _tool_match(self, checklist_path: str, documents_dir: str) -> Dict[str, Any]:
        checklist = self.checklist_parser.parse_file(checklist_path)
        docs = self._load_documents_from_dir(documents_dir)
        matches = self.matcher.match_pile(checklist, docs)
        return {
            "deal_name": checklist.deal_name,
            "total_checklist_items": len(checklist.items),
            "matches": [m.model_dump() for m in matches],
        }

    def _tool_detect_unsigned(self, documents_dir: str) -> Dict[str, Any]:
        docs = self._load_documents_from_dir(documents_dir)
        audits = []
        for d in docs:
            audits.append({
                "filename": d.original_filename,
                "detected_title": d.detected_title,
                "status": d.execution_status.value,
                "signatures": [s.model_dump() for s in d.signature_blocks],
            })
        return {"total_audited": len(docs), "documents": audits}

    def _tool_generate_report(self, checklist_path: str, documents_dir: str, output_path: str) -> Dict[str, Any]:
        checklist = self.checklist_parser.parse_file(checklist_path)
        docs = self._load_documents_from_dir(documents_dir)
        docs_map = {d.doc_id: d for d in docs}
        matches = self.matcher.match_pile(checklist, docs)
        return self.reporter.generate_report(checklist, matches, docs_map, output_path)

    def _load_documents_from_dir(self, documents_dir: str) -> List[DocumentMetadata]:
        docs = []
        for root, _, files in os.walk(documents_dir):
            for file in sorted(files):
                if file.startswith("."):
                    continue
                path = os.path.join(root, file)
                try:
                    meta = self.doc_parser.parse_file(path)
                    docs.append(meta)
                except Exception:
                    pass
        return docs
