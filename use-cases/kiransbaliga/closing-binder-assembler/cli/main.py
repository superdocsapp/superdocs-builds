"""Command-line interface for M&A Closing-Binder Assembler."""

import argparse
import json
import os
import sys
import time

from assembler.pdf_binder import PDFBinderAssembler
from core.enums import ExecutionStatus, MatchConfidence
from core.models import ClosingChecklist, DocumentMetadata, MatchResult
from exporter.folder_organizer import PerDocumentExporter
from exporter.outstanding_report import OutstandingReportGenerator
from matcher.semantic_matcher import SemanticMatcher
from parsers.checklist_parser import ChecklistParser
from parsers.document_parser import DocumentParser


def print_banner():
    print("=" * 80)
    print("   M&A CLOSING-BINDER ASSEMBLER (SuperDocs Task 2)")
    print("   Automated Semantic Matching, Execution Auditing & Navigable PDF Binder")
    print("=" * 80)


def run_assembler(
    checklist_path: str,
    documents_dir: str,
    output_dir: str,
    deal_title: str = None,
    dry_run: bool = False,
):
    print_banner()
    start_time = time.time()

    print(f"\n[1/5] Loading Closing Checklist from: {checklist_path}")
    checklist_parser = ChecklistParser()
    checklist = checklist_parser.parse_file(checklist_path)
    if deal_title:
        checklist.deal_name = deal_title
    print(f"      ✓ Deal: {checklist.deal_name}")
    print(f"      ✓ Target: {checklist.target_entity} | Buyer: {checklist.buyer_entity}")
    print(f"      ✓ Loaded {len(checklist.items)} checklist line items.")

    print(f"\n[2/5] Ingesting Transaction Documents from: {documents_dir}")
    doc_parser = DocumentParser()
    documents: list[DocumentMetadata] = []
    
    for root, _, files in os.walk(documents_dir):
        for f in sorted(files):
            if f.startswith(".") or f.endswith(".json") or f.endswith(".md"):
                continue
            fpath = os.path.join(root, f)
            try:
                meta = doc_parser.parse_file(fpath)
                documents.append(meta)
                status_icon = "✓" if meta.execution_status == ExecutionStatus.FULLY_EXECUTED else "⚠️"
                print(f"      {status_icon} Ingested '{f}' ({meta.file_type.upper()}, {meta.page_count}p) -> Status: {meta.execution_status.value}")
            except Exception as e:
                print(f"      ✗ Error parsing {f}: {e}")

    print(f"      ✓ Total Ingested Documents: {len(documents)}")

    print(f"\n[3/5] Executing Semantic Matching & Execution Status Auditing...")
    matcher = SemanticMatcher()
    matches = matcher.match_pile(checklist, documents)
    docs_map = {d.doc_id: d for d in documents}

    print("\n" + "-" * 80)
    print(f"{'Tab':<8} {'Checklist Item':<35} {'Matched File':<22} {'Status':<15}")
    print("-" * 80)
    for m in matches:
        item = next(it for it in checklist.items if it.item_id == m.checklist_item_id)
        fname = m.matched_filename or "[MISSING DELIVERABLE]"
        if len(fname) > 20:
            fname = fname[:18] + ".."
        title_snip = item.title[:33] + ".." if len(item.title) > 35 else item.title
        print(f"{item.tab_label:<8} {title_snip:<35} {fname:<22} {m.execution_status.value:<15}")
    print("-" * 80)

    if dry_run:
        print("\n[Dry Run Completed] Skipping file generation.")
        return

    os.makedirs(output_dir, exist_ok=True)
    pdf_binder_path = os.path.join(output_dir, "Closing_Binder_Master.pdf")
    print(f"\n[4/5] Assembling Navigable Master PDF Binder...")
    assembler = PDFBinderAssembler(output_dir=output_dir)
    final_pdf = assembler.assemble_binder(checklist, matches, docs_map, pdf_binder_path, checklist.deal_name)
    print(f"      ✓ Master PDF Binder assembled: {final_pdf}")

    print(f"\n[5/5] Exporting Deliverables Package...")
    per_doc_dir = os.path.join(output_dir, "Per_Document_Folder")
    exporter = PerDocumentExporter()
    folder_res = exporter.export_folder(checklist, matches, docs_map, per_doc_dir, create_zip=True)
    print(f"      ✓ Per-Document Directory: {folder_res['folder_path']}")
    if folder_res["zip_path"]:
        print(f"      ✓ Per-Document ZIP Archive: {folder_res['zip_path']}")

    report_base = os.path.join(output_dir, "Outstanding_Items_Report")
    reporter = OutstandingReportGenerator()
    rep_res = reporter.generate_report(checklist, matches, docs_map, report_base)
    print(f"      ✓ Client-Ready Outstanding Items PDF: {rep_res['pdf_path']}")
    print(f"      ✓ Client-Ready Outstanding Items MD:  {rep_res['md_path']}")
    print(f"      ✓ Closing Readiness Score: {rep_res['readiness_percentage']}%")

    elapsed = time.time() - start_time
    print(f"\n{'=' * 80}")
    print(f"   SUCCESSFULLY COMPLETED CLOSING BINDER ASSEMBLY IN {elapsed:.2f}s")
    print(f"   All 3 deliverables ready in: {output_dir}")
    print(f"{'=' * 80}\n")


def main():
    parser = argparse.ArgumentParser(description="M&A Closing-Binder Assembler CLI")
    parser.add_argument("--checklist", "-c", required=True, help="Path to closing checklist file (JSON/MD/CSV)")
    parser.add_argument("--documents-dir", "-d", required=True, help="Directory containing executed transaction files")
    parser.add_argument("--output-dir", "-o", default="./output_binder", help="Directory where outputs will be saved")
    parser.add_argument("--deal-title", "-t", help="Optional override for transaction title")
    parser.add_argument("--dry-run", action="store_true", help="Perform semantic matching and audit without building PDF")

    args = parser.parse_args()
    run_assembler(
        checklist_path=args.checklist,
        documents_dir=args.documents_dir,
        output_dir=args.output_dir,
        deal_title=args.deal_title,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
