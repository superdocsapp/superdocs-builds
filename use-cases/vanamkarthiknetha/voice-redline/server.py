"""VoiceRedline server — a thin local bridge between the browser voice UI
and SuperDocs.

Why a server at all: the SuperDocs API key must never reach the browser,
and chat jobs take 30s-minutes, longer than a comfortable single HTTP
request. So the browser talks to this localhost app; slow SuperDocs work
runs in background threads and the browser polls cheap status endpoints.

State is in-memory on purpose: this is a single-user desk tool, and the
durable state (documents, sessions, jobs) already lives in SuperDocs.

Run:  uvicorn server:app --port 8765
"""
import io
import threading
import time
import uuid

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import superdocs_client as sd

app = FastAPI(title="VoiceRedline")

DOCS = {}    # doc_id -> {session, filename, edits: [edit_id, ...]}
EDITS = {}   # edit_id -> {status, progress, doc_id, edit(dict from client), ...}
LOCK = threading.Lock()

EXPORT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html",
    "txt": "text/plain",
}


def _progress(edit_id):
    def cb(msg):
        with LOCK:
            if edit_id in EDITS:
                EDITS[edit_id]["progress"] = msg
    return cb


def _run_edit(edit_id, session, instruction):
    try:
        edit = sd.open_edit(session, instruction, _progress(edit_id))
        with LOCK:
            rec = EDITS[edit_id]
            rec["edit"] = edit
            if edit["pending"]:
                rec["status"] = "awaiting"
            elif edit["draft_html"]:
                # BUGS B6: drafting bypasses the server-side gate - content is
                # already committed. Gate it locally as one synthetic change.
                rec["status"] = "awaiting"
                rec["gated_draft"] = True
            else:
                rec["status"] = "done"  # chat reply with no doc change (Q&A)
    except Exception as exc:  # surface every failure to the UI, never crash the thread
        with LOCK:
            EDITS[edit_id].update(status="failed", error=str(exc))


def _run_decisions(edit_id, decisions):
    try:
        rec = EDITS[edit_id]
        state = sd.decide(rec["edit"], decisions, _progress(edit_id))
        with LOCK:
            rec["status"] = "done" if state == "completed" else "rejected"
    except Exception as exc:
        with LOCK:
            EDITS[edit_id].update(status="failed", error=str(exc))


@app.post("/api/documents")
async def create_document(file: UploadFile | None = None):
    """Upload a document (docx/html/txt) or start blank for voice drafting."""
    data = await file.read() if file else None
    name = file.filename if file else "draft.html"
    try:
        session = sd.upload_doc(data, name)
    except sd.SuperDocsError as exc:
        raise HTTPException(502, str(exc))
    doc_id = uuid.uuid4().hex[:8]
    with LOCK:
        DOCS[doc_id] = {"session": session, "filename": name, "edits": []}
    return {"doc_id": doc_id, "filename": name}


class EditIn(BaseModel):
    instruction: str


@app.post("/api/documents/{doc_id}/edits")
def create_edit(doc_id: str, body: EditIn):
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "unknown document")
    edit_id = uuid.uuid4().hex[:8]
    with LOCK:
        EDITS[edit_id] = {"status": "working", "progress": "Requesting edit...",
                          "doc_id": doc_id, "instruction": body.instruction,
                          "gated_draft": False, "started": time.time()}
        doc["edits"].append(edit_id)
    threading.Thread(target=_run_edit,
                     args=(edit_id, doc["session"], body.instruction),
                     daemon=True).start()
    return {"edit_id": edit_id}


@app.get("/api/edits/{edit_id}")
def edit_status(edit_id: str):
    rec = EDITS.get(edit_id)
    if not rec:
        raise HTTPException(404, "unknown edit")
    out = {"status": rec["status"], "progress": rec.get("progress", ""),
           "gated_draft": rec["gated_draft"], "error": rec.get("error")}
    edit = rec.get("edit")
    if edit and rec["status"] in ("awaiting", "done", "rejected"):
        if rec["gated_draft"]:
            # Present the locally-gated draft as one synthetic pending change.
            out["pending"] = [{"change_id": "local-draft", "old_html": "",
                               "new_html": edit["draft_html"],
                               "ai_explanation": "Drafted new content for this "
                               "document (locally gated - see README on B6)."}]
        else:
            out["pending"] = [{k: c.get(k) for k in
                               ("change_id", "old_html", "new_html", "ai_explanation")}
                              for c in edit["pending"]]
        out["summary"] = edit["summary"]
        out["response"] = edit["response"]
    return out


class DecisionsIn(BaseModel):
    decisions: list[dict]


@app.post("/api/edits/{edit_id}/decisions")
def send_decisions(edit_id: str, body: DecisionsIn):
    rec = EDITS.get(edit_id)
    if not rec:
        raise HTTPException(404, "unknown edit")
    if rec["status"] != "awaiting":
        raise HTTPException(409, f"edit is {rec['status']}, not awaiting")
    if rec["gated_draft"]:
        # Content is already committed server-side (B6); the local gate decides
        # whether we treat the session as good (export) or abandoned.
        approved = any(d.get("approved") for d in body.decisions)
        with LOCK:
            rec["status"] = "done" if approved else "rejected"
        return {"ok": True, "local": True}
    # The SuperDocs approve endpoint accepts decisions for change_ids that do
    # not exist and completes the job anyway (found while building this app),
    # so validate against the real pending set before forwarding.
    known = {c["change_id"] for c in rec["edit"]["pending"]}
    sent = {d.get("change_id") for d in body.decisions}
    if sent - known:
        raise HTTPException(400, f"unknown change_ids: {sorted(sent - known)}")
    if known - sent:
        raise HTTPException(400, f"undecided change_ids: {sorted(known - sent)}")
    with LOCK:
        rec["status"] = "applying"
        rec["progress"] = "Sending decisions..."
    threading.Thread(target=_run_decisions, args=(edit_id, body.decisions),
                     daemon=True).start()
    return {"ok": True}


@app.get("/api/documents/{doc_id}/export")
def export(doc_id: str, fmt: str = "docx"):
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "unknown document")
    if fmt not in EXPORT_TYPES:
        raise HTTPException(400, f"format must be one of {list(EXPORT_TYPES)}")
    try:
        blob = sd.export_doc(doc["session"], fmt)
    except sd.SuperDocsError as exc:
        raise HTTPException(502, str(exc))
    stem = doc["filename"].rsplit(".", 1)[0] or "document"
    return StreamingResponse(
        io.BytesIO(blob), media_type=EXPORT_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{stem}.{fmt}"'})


@app.get("/api/documents/{doc_id}/preview")
def preview(doc_id: str):
    """HTML export rendered in the UI's sandboxed iframe after each applied
    round. Exports are non-billable, so the live preview costs nothing."""
    doc = DOCS.get(doc_id)
    if not doc:
        raise HTTPException(404, "unknown document")
    try:
        blob = sd.export_doc(doc["session"], "html")
    except sd.SuperDocsError as exc:
        raise HTTPException(502, str(exc))
    return StreamingResponse(io.BytesIO(blob), media_type="text/html")


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/sample")
def sample():
    return FileResponse("sample/northvoice-brightline-msa.html")
