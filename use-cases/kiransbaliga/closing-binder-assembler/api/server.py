"""FastAPI backend server for M&A Closing-Binder Assembler Web UI & API."""

import os
import shutil
import tempfile
from typing import Dict, List, Optional
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from assembler.pdf_binder import PDFBinderAssembler
from core.models import AssemblyResult, ClosingChecklist, DocumentMetadata, MatchResult
from exporter.folder_organizer import PerDocumentExporter
from exporter.outstanding_report import OutstandingReportGenerator
from matcher.semantic_matcher import SemanticMatcher
from parsers.checklist_parser import ChecklistParser
from parsers.document_parser import DocumentParser

app = FastAPI(
    title="M&A Closing-Binder Assembler API",
    description="Automated M&A Closing Binder Assembler for Legal Associates & Transactional Paralegals",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE = {
    "checklist": None,
    "documents": [],
    "matches": [],
    "last_result": None,
    "temp_dir": tempfile.mkdtemp(prefix="closing_binder_"),
}

checklist_parser = ChecklistParser()
doc_parser = DocumentParser()
matcher = SemanticMatcher()
assembler = PDFBinderAssembler()
exporter = PerDocumentExporter()
reporter = OutstandingReportGenerator()


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    ui_index_path = os.path.join(os.path.dirname(__file__), "..", "ui", "index.html")
    if os.path.exists(ui_index_path):
        with open(ui_index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>M&A Closing-Binder Assembler</h1><p>UI file not found.</p>"


@app.post("/api/checklist/upload")
async def upload_checklist(file: UploadFile = File(...)):
    dest_path = os.path.join(STATE["temp_dir"], file.filename)
    with open(dest_path, "wb") as f:
        content = await file.read()
        f.write(content)

    checklist = checklist_parser.parse_file(dest_path)
    STATE["checklist"] = checklist
    return {
        "status": "SUCCESS",
        "deal_name": checklist.deal_name,
        "buyer": checklist.buyer_entity,
        "target": checklist.target_entity,
        "total_items": len(checklist.items),
        "items": [it.dict() for it in checklist.items],
    }


@app.post("/api/checklist/load-sample")
async def load_sample_checklist():
    sample_path = os.path.join(os.path.dirname(__file__), "..", "samples", "project_titan_checklist.json")
    checklist = checklist_parser.parse_file(sample_path)
    STATE["checklist"] = checklist
    return {
        "status": "SUCCESS",
        "deal_name": checklist.deal_name,
        "buyer": checklist.buyer_entity,
        "target": checklist.target_entity,
        "total_items": len(checklist.items),
        "items": [it.dict() for it in checklist.items],
    }


@app.post("/api/documents/upload-bundle")
async def upload_documents(files: List[UploadFile] = File(...)):
    docs_dir = os.path.join(STATE["temp_dir"], "uploaded_docs")
    os.makedirs(docs_dir, exist_ok=True)
    parsed_docs = []

    for file in files:
        fpath = os.path.join(docs_dir, file.filename)
        with open(fpath, "wb") as f:
            f.write(await file.read())
        try:
            meta = doc_parser.parse_file(fpath)
            parsed_docs.append(meta)
        except Exception:
            pass

    STATE["documents"] = parsed_docs
    return {
        "status": "SUCCESS",
        "total_uploaded": len(parsed_docs),
        "documents": [d.dict() for d in parsed_docs],
    }


@app.post("/api/documents/load-sample-corpus")
async def load_sample_corpus():
    sample_docs_dir = os.path.join(os.path.dirname(__file__), "..", "samples", "executed_documents")
    parsed_docs = []
    for root, _, files in os.walk(sample_docs_dir):
        for f in sorted(files):
            if f.startswith("."):
                continue
            path = os.path.join(root, f)
            try:
                meta = doc_parser.parse_file(path)
                parsed_docs.append(meta)
            except Exception:
                pass

    STATE["documents"] = parsed_docs
    return {
        "status": "SUCCESS",
        "total_loaded": len(parsed_docs),
        "documents": [d.dict() for d in parsed_docs],
    }


@app.get("/api/matches")
async def get_semantic_matches():
    if not STATE["checklist"]:
        raise HTTPException(status_code=400, detail="Please upload a closing checklist first.")
    
    matches = matcher.match_pile(STATE["checklist"], STATE["documents"])
    STATE["matches"] = matches
    return {
        "deal_name": STATE["checklist"].deal_name,
        "total_items": len(STATE["checklist"].items),
        "matches": [m.dict() for m in matches],
    }


@app.post("/api/assemble")
async def assemble_binder(deal_title: Optional[str] = Form(None)):
    if not STATE["checklist"]:
        raise HTTPException(status_code=400, detail="Checklist not loaded.")
    if not STATE["matches"]:
        STATE["matches"] = matcher.match_pile(STATE["checklist"], STATE["documents"])

    out_dir = os.path.join(STATE["temp_dir"], "output_binder")
    os.makedirs(out_dir, exist_ok=True)

    checklist = STATE["checklist"]
    matches = STATE["matches"]
    docs_map = {d.doc_id: d for d in STATE["documents"]}

    pdf_path = os.path.join(out_dir, "Closing_Binder_Master.pdf")
    assembler.assemble_binder(checklist, matches, docs_map, pdf_path, deal_title or checklist.deal_name)

    folder_dir = os.path.join(out_dir, "Per_Document_Folder")
    folder_res = exporter.export_folder(checklist, matches, docs_map, folder_dir, create_zip=True)

    report_base = os.path.join(out_dir, "Outstanding_Items_Report")
    rep_res = reporter.generate_report(checklist, matches, docs_map, report_base)

    result = {
        "status": "SUCCESS",
        "deal_name": checklist.deal_name,
        "readiness_percentage": rep_res["readiness_percentage"],
        "is_closing_ready": rep_res["is_closing_ready"],
        "pdf_binder_path": pdf_path,
        "per_document_zip_path": folder_res["zip_path"],
        "outstanding_report_pdf_path": rep_res["pdf_path"],
        "outstanding_report_md_path": rep_res["md_path"],
    }
    STATE["last_result"] = result
    return result


@app.get("/api/download/binder-pdf")
async def download_binder_pdf():
    if not STATE["last_result"] or not os.path.exists(STATE["last_result"]["pdf_binder_path"]):
        raise HTTPException(status_code=404, detail="Binder not assembled yet.")
    return FileResponse(
        STATE["last_result"]["pdf_binder_path"],
        media_type="application/pdf",
        filename="Closing_Binder_Master.pdf",
    )


@app.get("/api/download/per-document-zip")
async def download_per_document_zip():
    if not STATE["last_result"] or not STATE["last_result"]["per_document_zip_path"]:
        raise HTTPException(status_code=404, detail="Zip not found.")
    return FileResponse(
        STATE["last_result"]["per_document_zip_path"],
        media_type="application/zip",
        filename="Per_Document_Closing_Binder.zip",
    )


@app.get("/api/download/outstanding-report-pdf")
async def download_outstanding_report_pdf():
    if not STATE["last_result"] or not os.path.exists(STATE["last_result"]["outstanding_report_pdf_path"]):
        raise HTTPException(status_code=404, detail="Report not generated.")
    return FileResponse(
        STATE["last_result"]["outstanding_report_pdf_path"],
        media_type="application/pdf",
        filename="Outstanding_Items_Report.pdf",
    )
