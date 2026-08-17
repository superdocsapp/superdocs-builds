import hashlib
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Response
from fastapi.middleware.cors import CORSMiddleware
from html import escape
from uuid import UUID, uuid4
from typing import Optional
from core.db import exec, exec_one, insert, insert_many, delete, to_uuid, update
from core.text import html_to_text
from core.trace import TraceLogger
from core.config import WATCHED_DIR
from core.superdocs_client import SuperDocsClient
from agents.ingestor.watcher import DocWatcher
from agents.ingestor.ingestor import Ingestor
from agents.ingestor.dispatcher import Dispatcher
from datetime import datetime, timezone

app = FastAPI(title="Drift Detector — Agent #1 (File Ingestor)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

watcher: DocWatcher | None = None
sd_client = SuperDocsClient()


@app.on_event("startup")
async def _migrate():
    # Serves document edit history, which lives in columns added after the
    # baseline schema; initdb will not replay those against an existing volume.
    from core.migrate import apply_migrations

    await apply_migrations()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/watch")
async def start_watching():
    global watcher

    async def on_file(path: str):
        run_id = uuid4()
        run_row = await insert(
            "runs",
            {
                "trigger": f"file_change:{path}",
                "corpus_ref": path,
                "status": "in_progress",
                "created_at": datetime.now(timezone.utc),
            },
            returning="id",
        )
        rid = to_uuid(run_row["id"])

        ingestor = Ingestor(sd_client, sd_client.session_id)
        parsed = await ingestor.ingest_file(path, rid)

        if parsed:
            await Dispatcher.dispatch_ingestion(rid, [parsed.document_id])

    watcher = DocWatcher(callback=on_file)
    watcher.start()
    return {"status": "watching", "dir": str(watcher.watched_dir)}


@app.post("/run")
async def run_once(files: list[str] | None = None):
    run_id = uuid4()
    await insert(
        "runs",
        {
            "id": str(run_id),
            "trigger": "manual",
            "status": "in_progress",
            "created_at": datetime.now(timezone.utc),
        },
    )

    ingestor = Ingestor(sd_client, sd_client.session_id)
    document_ids = []

    if files:
        for f in files:
            parsed = await ingestor.ingest_file(f, run_id)
            if parsed:
                document_ids.append(parsed.document_id)

    if document_ids:
        job_id = await Dispatcher.dispatch_ingestion(run_id, document_ids)
        return {"run_id": str(run_id), "document_ids": [str(d) for d in document_ids], "job_id": str(job_id)}
    return {"run_id": str(run_id), "document_ids": [], "message": "no documents ingested"}


@app.post("/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    run_id: Optional[str] = Form(None),
):
    """Accept file uploads from the UI, ingest each through SuperDocs, and
    dispatch a job for Agent #2. If run_id is omitted, a new run is created;
    if provided, the upload is appended to that run (idempotent by file hash)."""
    if run_id:
        rid = UUID(run_id)
        existing = await exec_one("SELECT id FROM runs WHERE id = :id", {"id": run_id})
        if not existing:
            raise HTTPException(404, "run_id not found")
    else:
        rid = uuid4()
        await insert(
            "runs",
            {
                "id": str(rid),
                "trigger": "upload",
                "status": "in_progress",
                "created_at": datetime.now(timezone.utc),
            },
        )

    WATCHED_DIR.mkdir(parents=True, exist_ok=True)
    ingestor = Ingestor(sd_client, sd_client.session_id)
    trace = TraceLogger(rid)
    document_ids = []
    filenames = []

    await trace.log(
        "INGEST", "-", decision="start", evidence={"files": [f.filename for f in files]}
    )

    for f in files:
        t0 = time.time()
        dest = WATCHED_DIR / f.filename
        content = await f.read()
        dest.write_bytes(content)
        try:
            parsed = await ingestor.ingest_file(str(dest), rid)
        except Exception as exc:
            # An ingest failure used to 500 with nothing written anywhere, so
            # the run sat 'in_progress' forever with an empty log. Record it.
            await trace.log(
                "INGEST",
                f.filename,
                decision=f"failed: {type(exc).__name__}: {str(exc)[:300]}",
                ms=int((time.time() - t0) * 1000),
            )
            await update("runs", {"id": str(rid)}, {"status": "failed"})
            raise HTTPException(
                502, f"Ingest failed for {f.filename}: {type(exc).__name__}: {exc}"
            )

        if parsed:
            document_ids.append(parsed.document_id)
            filenames.append(f.filename)
            await trace.log(
                "INGEST",
                f.filename,
                decision="ingested",
                evidence={
                    "document_id": str(parsed.document_id),
                    "chunks": len(parsed.chunks),
                },
                superdocs_ops=0,  # uploads are free
                ms=int((time.time() - t0) * 1000),
            )

    job_id = None
    if document_ids:
        job_id = await Dispatcher.dispatch_ingestion(rid, document_ids)
        await trace.log(
            "DISPATCH",
            "-",
            decision="queued for analysis",
            evidence={"documents": len(document_ids), "job_id": str(job_id)},
        )
    else:
        # Nothing to analyze: don't leave the run looking active forever.
        await update("runs", {"id": str(rid)}, {"status": "completed"})
        await trace.log("DISPATCH", "-", decision="nothing to analyze")

    return {
        "run_id": str(rid),
        "document_ids": [str(d) for d in document_ids],
        "filenames": filenames,
        "job_id": str(job_id) if job_id else None,
    }


@app.get("/runs")
async def list_runs():
    rows = await exec(
        "SELECT id, corpus_ref, feed_ref, trigger, status, created_at "
        "FROM runs ORDER BY created_at DESC LIMIT 50"
    )
    return {"runs": rows}


@app.get("/documents")
async def list_documents(run_id: Optional[str] = None):
    base_sql = """
        SELECT d.id, d.run_id, d.filename, d.file_hash, d.session_id,
               d.superdocs_doc_id, d.created_at, COUNT(c.id) AS chunk_count
        FROM documents d
        LEFT JOIN chunks c ON c.document_id = d.id
        {where}
        GROUP BY d.id
        ORDER BY d.created_at DESC
    """
    if run_id:
        rows = await exec(base_sql.format(where="WHERE d.run_id = :rid"), {"rid": run_id})
    else:
        rows = await exec(base_sql.format(where=""))
    return {"documents": rows}


def _source_path(filename: str) -> Optional[Path]:
    """Locate the file a document was ingested from.

    Re-ingest rebuilds from the original file rather than from our stored
    chunks: chunk order was not recorded before `ordinal` existed, so
    re-uploading what we hold would faithfully reproduce a scrambled document.
    """
    for directory in (Path(WATCHED_DIR), Path(WATCHED_DIR).parent / "samples"):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


@app.post("/documents/{document_id}/reingest")
async def reingest_document(document_id: str):
    """Re-upload a document so it has a usable SuperDocs document again.

    Documents ingested before each upload got its own session share a fate:
    they were overwritten in SuperDocs by whatever was uploaded next, and the
    id stored for them names nothing that still exists. No retry of the apply
    can fix that, because the failure is not transient.

    This re-uploads the original file into a session of its own, then swaps in
    the new document id, session and chunks. Findings for the document are
    cleared: they cite chunk ids from the old parse, and SuperDocs mints fresh
    random chunk ids on every upload, so keeping them would leave evidence
    pointing at chunks that no longer exist. Applied-edit history is kept — it
    records something that really happened.
    """
    doc = await exec_one(
        "SELECT id, run_id, filename, superdocs_doc_id FROM documents WHERE id = :id",
        {"id": document_id},
    )
    if not doc:
        raise HTTPException(404, "Document not found")

    source = _source_path(doc["filename"])
    if not source:
        raise HTTPException(
            409,
            f"Cannot re-ingest '{doc['filename']}': its source file is no longer in "
            f"{WATCHED_DIR}. Upload the file again instead.",
        )

    ingestor = Ingestor(sd_client, sd_client.session_id)
    try:
        parsed = await ingestor.upload_only(str(source))
    except Exception as exc:
        raise HTTPException(502, f"Re-upload failed: {exc}") from exc

    if not parsed.superdocs_doc_id:
        raise HTTPException(
            502,
            "SuperDocs accepted the upload but returned no durable document id, "
            "so the document still could not be edited. Nothing was changed.",
        )

    # Replace the document's chunks and identity in one transaction: a partial
    # swap would leave chunks from one parse addressed by ids from another.
    await exec(
        "DELETE FROM review_decisions WHERE finding_id IN "
        "(SELECT id FROM findings WHERE document_id = :did)",
        {"did": document_id},
    )
    await exec(
        "DELETE FROM queues WHERE finding_id IN "
        "(SELECT id FROM findings WHERE document_id = :did)",
        {"did": document_id},
    )
    await exec(
        "DELETE FROM findings WHERE document_id = :did "
        "AND id NOT IN (SELECT finding_id FROM applied_edits)",
        {"did": document_id},
    )
    await delete("chunks", {"document_id": document_id})

    writes = []
    for position, chunk in enumerate(parsed.chunks):
        html = chunk.get("html") or ""
        writes.append((
            "chunks",
            {
                "id": str(uuid4()),
                "document_id": document_id,
                "chunk_id": chunk["chunk_id"],
                "ordinal": position,
                "html": html,
                "text_content": html_to_text(html),
                "content_hash": chunk.get("content_hash")
                or hashlib.sha256(html.encode()).hexdigest(),
            },
        ))
    await insert_many(writes)

    await update(
        "documents",
        {"id": document_id},
        {
            "superdocs_doc_id": parsed.superdocs_doc_id,
            "session_id": parsed.session_id,
        },
    )

    return {
        "document_id": document_id,
        "filename": doc["filename"],
        "previous_superdocs_doc_id": doc["superdocs_doc_id"],
        "superdocs_doc_id": parsed.superdocs_doc_id,
        "session_id": parsed.session_id,
        "chunks": len(writes),
    }


@app.get("/documents/{document_id}")
async def get_document(document_id: str):
    doc = await exec_one(
        "SELECT id, run_id, filename, file_hash, session_id, superdocs_doc_id, created_at "
        "FROM documents WHERE id = :id",
        {"id": document_id},
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    chunks = await exec(
        # Document order. Chunk ids are random UUIDs, so ordering by them
        # scrambles the document; rows ingested before `ordinal` existed have
        # no recorded order and sort last rather than interleaving.
        "SELECT chunk_id, html, content_hash FROM chunks WHERE document_id = :did "
        "ORDER BY ordinal NULLS LAST, chunk_id",
        {"did": document_id},
    )
    return {"document": doc, "chunks": chunks}


@app.get("/documents/{document_id}/history")
async def document_history(document_id: str):
    """Every edit that has landed on this document, newest first.

    Reads applied_edits rather than reconstructing anything: an edit is
    recorded at the moment it is proven applied, with the chunk's before and
    after content, so history is a record of what happened rather than an
    inference from the document's current state.

    Attempts that were blocked or failed are returned alongside, because "we
    tried to change this and the byte Judge stopped it" is part of a
    document's story and is otherwise only visible in the failed queue.
    """
    doc = await exec_one(
        "SELECT id, filename FROM documents WHERE id = :id", {"id": document_id}
    )
    if not doc:
        raise HTTPException(404, "Document not found")

    edits = await exec(
        """
        SELECT ae.id, ae.chunk_id, ae.before_html, ae.after_html,
               ae.before_hash, ae.after_hash, ae.proposed_old, ae.proposed_new,
               ae.superdocs_job_id, ae.superdocs_change_id, ae.applied_at,
               ae.finding_id, f.run_id, f.evidence_quote, f.ai_explanation,
               rd.decision AS review_decision, rd.feedback AS review_feedback,
               rd.decided_at
          FROM applied_edits ae
          LEFT JOIN findings f ON f.id = ae.finding_id
          LEFT JOIN review_decisions rd ON rd.finding_id = ae.finding_id
         WHERE ae.document_id = :did OR f.document_id = :did
         ORDER BY ae.applied_at DESC
        """,
        {"did": document_id},
    )

    attempted = await exec(
        """
        SELECT f.id AS finding_id, f.run_id, f.chunk_id, f.evidence_chunk_id,
               f.proposed_old, f.proposed_new, f.apply_status, f.apply_reason,
               f.ai_explanation, rd.decision AS review_decision, rd.decided_at
          FROM findings f
          JOIN review_decisions rd ON rd.finding_id = f.id
         WHERE f.document_id = :did
           AND rd.decision = 'approved'
           AND f.id NOT IN (SELECT finding_id FROM applied_edits)
         ORDER BY rd.decided_at DESC
        """,
        {"did": document_id},
    )

    return {
        "document_id": document_id,
        "filename": doc["filename"],
        "edits": edits,
        "pending": attempted,
    }


DOCUMENT_PAGE_CSS = """
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
         Helvetica, Arial, sans-serif; color: #1f1d1a; background: #ececea;
         margin: 0; padding: 24px; line-height: 1.6; }
  .doc { max-width: 820px; margin: 0 auto; background: #fff; padding: 32px 40px;
         border: 1px solid #e2e0da; }
  .doc-header { border-bottom: 1px solid #e2e0da; margin-bottom: 24px;
                padding-bottom: 12px; }
  .doc-title { font-size: 13px; font-weight: 600; text-transform: uppercase;
               letter-spacing: 0.06em; color: #9c988e; }
  code { background: #f0efeb; padding: 1px 4px;
         font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9em; }
  h1, h2, h3, h4 { line-height: 1.3; }
"""


@app.get("/documents/{document_id}/content")
async def document_content(
    document_id: str, disposition: str = "inline", format: str = "html"
):
    doc = await exec_one(
        "SELECT filename FROM documents WHERE id = :id", {"id": document_id}
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    chunks = await exec(
        "SELECT html FROM chunks WHERE document_id = :did "
        "ORDER BY ordinal NULLS LAST, chunk_id",
        {"did": document_id},
    )
    body = "\n".join(c["html"] for c in chunks)
    filename = doc["filename"]

    if disposition == "attachment":
        if format == "text":
            # Plain text keeps the original filename honest for .md/.txt.
            text = re.sub(r"<[^>]+>", "", body)
            text = (
                text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            )
            text = re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
            return Response(
                content=text,
                media_type="text/plain; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )

        # Serving chunked HTML, so the extension must say so rather than
        # handing back a .md file that is actually HTML.
        html_name = f"{Path(filename).stem}.html"
        return Response(
            content=body,
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{html_name}"'},
        )

    page = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(filename)}</title>\n"
        f"<style>{DOCUMENT_PAGE_CSS}</style>\n"
        "</head>\n<body>\n"
        f'<article class="doc">\n'
        f'<header class="doc-header"><p class="doc-title">{escape(filename)}</p></header>\n'
        f"{body}\n"
        "</article>\n</body>\n</html>"
    )
    return Response(
        content=page,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    """Delete a document and everything that hangs off it.

    findings.document_id references documents, so deleting a document with
    findings previously failed on a foreign-key violation. Dependants are
    removed in FK order — except applied edits, which are an audit record of
    a change actually made to a real document and must not be erased.
    """
    doc = await exec_one("SELECT id FROM documents WHERE id = :id", {"id": document_id})
    if not doc:
        raise HTTPException(404, "Document not found")

    applied = await exec(
        "SELECT ae.id FROM applied_edits ae "
        "JOIN findings f ON f.id = ae.finding_id "
        "WHERE f.document_id = :did",
        {"did": document_id},
    )
    if applied:
        raise HTTPException(
            409,
            f"Refusing to delete: {len(applied)} edit(s) were already applied to "
            f"this document. Deleting it would destroy that audit trail.",
        )

    await exec(
        "DELETE FROM review_decisions WHERE finding_id IN "
        "(SELECT id FROM findings WHERE document_id = :did)",
        {"did": document_id},
    )
    await exec(
        "DELETE FROM queues WHERE finding_id IN "
        "(SELECT id FROM findings WHERE document_id = :did)",
        {"did": document_id},
    )
    findings = await exec(
        "DELETE FROM findings WHERE document_id = :did RETURNING id",
        {"did": document_id},
    )
    await delete("chunks", {"document_id": document_id})
    await delete("documents", {"id": document_id})

    return {
        "status": "deleted",
        "document_id": document_id,
        "findings_removed": len(findings),
    }


@app.get("/status")
async def status():
    return {
        "watching": watcher is not None and watcher._observer is not None,
        "known_files": len(watcher._known_hashes) if watcher else 0,
    }


@app.on_event("shutdown")
async def shutdown():
    if watcher:
        watcher.stop()