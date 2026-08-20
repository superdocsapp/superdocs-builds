"""
main.py -- FastAPI app for the Healthcare Compliance Workspace.

Rebuilt from scratch on the Workspace -> Document -> DocumentVersion ->
Section -> SectionSnapshot -> ProcedurePolicyReference schema (see
models.py / the schema design chat). There is no hardcoded demo pack
anywhere in this file -- every Workspace, Document, and reference
originates from a real human action through these endpoints.

Endpoint groups, in the order data flows through the system:

  SETUP
  1. POST /workspaces                                create a workspace
  2. POST /workspaces/{id}/documents/upload           upload+group a real file
  3. GET  /workspaces/{id}/documents                  list, grouped
  4. GET  /documents/{id}                             detail incl. sections
  4b. DELETE /documents/{id}                          delete (cascades locally,
                                                        blocked on a policy with
                                                        linked procedures)
  5. POST /workspaces/{id}/analyze                    Analyze References job
  6. GET  /workspaces/{id}/references                 the graph
  7. POST /workspaces/{id}/validate                   independent re-check
  8. GET  /workspaces/{id}/findings                   open problems

  MAINTENANCE
  9.  POST /documents/{id}/update-requests            propose an edit
  10. GET  /workspaces/{id}/proposed-changes           review queue (enriches
                                                        pending SuperDocs jobs)
  11. POST /proposed-changes/{id}/approve              approve/reject one change
                                                        -- commits a new
                                                        DocumentVersion, and for
                                                        policy edits, propagates
                                                        to every affected
                                                        procedure via the
                                                        reference graph

  REPORTING
  12. POST /workspaces/{id}/reports                   generate a report
  13. GET  /workspaces/{id}/reports                   list reports
  14. GET  /export/{document_id}                       export one document
  15. GET  /workspaces/{id}/export                      zip active versions + report
  16. GET  /workspaces/{id}/change-events               audit log
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select

import chunking
import db
import llm_client
import models
from superdocs_client import SuperDocsClient, SuperDocsError

load_dotenv()

app = FastAPI(title="Healthcare Compliance Workspace API")

# Origins allowed to call this API. Defaults to localhost (any port, for
# local dev) plus any Vercel deployment (preview or prod -- Vercel gives
# every branch/PR its own *.vercel.app subdomain, so a fixed single-origin
# allowlist would break on the very first preview deploy). Override with a
# real regex via CORS_ORIGIN_REGEX once you have a custom domain, e.g.
# CORS_ORIGIN_REGEX='https://(www\.)?your-domain\.com' -- see README's
# Deployment section.
_CORS_ORIGIN_REGEX = os.environ.get(
    "CORS_ORIGIN_REGEX",
    r"http://localhost:\d+|https://.*\.vercel\.app",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIDENCE_AUTO_ACCEPT = 0.85  # >= this: reference created as VALID
CONFIDENCE_MIN = 0.5           # below this: not even recorded as a candidate
DEFAULT_ANALYSIS_CONCURRENCY = 3

_SOURCE_FORMAT_BY_EXT = {
    "pdf": models.SourceFormat.PDF,
    "docx": models.SourceFormat.DOCX,
    "doc": models.SourceFormat.DOCX,
    "txt": models.SourceFormat.TXT,
    "html": models.SourceFormat.HTML,
    "htm": models.SourceFormat.HTML,
    "md": models.SourceFormat.MD,
    "rtf": models.SourceFormat.RTF,
}

_EXPORT_CONTENT_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html",
    "markdown": "text/markdown",
    "txt": "text/plain",
}


def get_client() -> SuperDocsClient:
    import os

    api_key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    base_url = os.environ.get("SUPERDOCS_API_BASE", "https://api.superdocs.app").strip()
    if not api_key:
        raise HTTPException(500, "SUPERDOCS_API_KEY not configured")
    return SuperDocsClient(api_key=api_key, base_url=base_url)


def get_llm_client() -> llm_client.LLMClient:
    import os

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(500, "GROQ_API_KEY not configured -- required for Analyze References")
    return llm_client.LLMClient(api_key=api_key)


# ============================================================================
# templates -- the surface this build's card names but the app never called
# ============================================================================
#
# docs.superdocs.app/concepts/templates: you upload a template once (it
# persists at the account/org level), and the AI searches your uploaded
# templates and uses one as a starting point whenever you ask it to draft a
# document from scratch (POST /v1/chat with no document_html -- see
# "Creating documents from scratch" in docs.superdocs.app/concepts/documents).
# There's no separate "instantiate this template" endpoint; templates work
# by being *available* for the AI to find and apply during a normal chat
# turn.
#
# TEMPLATE_LIBRARY intentionally holds STRUCTURE ONLY -- section headings
# and a one-line instruction per section, never actual policy language. That
# distinction matters here specifically: this project's whole selling point
# is "no hardcoded organization, no seed data, no demo pack anywhere in this
# codebase" (see README). A template that shipped real HIPAA policy text
# would quietly reintroduce a seed pack through the back door. A blank
# skeleton the AI still has to fill in based on your prompt does not.
TEMPLATE_LIBRARY: list[dict[str, str]] = [
    {
        "filename": "policy-template.html",
        "html": (
            "<h1>[Policy Title]</h1>"
            "<h2>Purpose</h2><p>[State what this policy governs and why it exists.]</p>"
            "<h2>Scope</h2><p>[Who and what this policy applies to.]</p>"
            "<h2>Policy Statement</h2><p>[The actual rule(s) this policy establishes.]</p>"
            "<h2>Roles &amp; Responsibilities</h2><p>[Who is accountable for what.]</p>"
            "<h2>Enforcement</h2><p>[Consequences of non-compliance.]</p>"
            "<h2>Review Schedule</h2><p>[How often this policy is reviewed and by whom.]</p>"
        ),
    },
    {
        "filename": "procedure-template.html",
        "html": (
            "<h1>[Procedure Title]</h1>"
            "<h2>Purpose</h2><p>[What this procedure implements and which policy it belongs to.]</p>"
            "<h2>Trigger Conditions</h2><p>[When this procedure is followed.]</p>"
            "<h2>Steps</h2><p>[Numbered, actionable steps.]</p>"
            "<h2>Escalation</h2><p>[Who to involve if a step can't be completed.]</p>"
            "<h2>Post-Procedure Review</h2><p>[How completion is verified and logged.]</p>"
        ),
    },
]


def _ensure_templates_uploaded(client: SuperDocsClient) -> None:
    """
    Idempotent by design (matches the assignment's "idempotency wherever an
    operation costs money" bar): list_templates is documented non-billable,
    so we always check what's already there before uploading anything, and
    only upload entries whose filename isn't present yet. Safe to call on
    every request that needs templates to exist -- steady state costs one
    free GET and zero uploads.
    """
    existing = client.list_templates()
    existing_filenames = {t.get("filename") for t in existing.get("templates", [])}
    for entry in TEMPLATE_LIBRARY:
        if entry["filename"] in existing_filenames:
            continue
        client.upload_template_base64(filename=entry["filename"], html_or_bytes=entry["html"])


@app.get("/templates")
def list_templates():
    """
    Surfaces what's actually uploaded on the SuperDocs side (not just our
    local TEMPLATE_LIBRARY constant), so this reflects reality even if
    someone adds/removes templates directly through the SuperDocs web app.
    """
    client = get_client()
    _ensure_templates_uploaded(client)
    return client.list_templates()


def _safe_debug(obj, max_len: int = 400) -> str:
    """Truncated, best-effort repr of a raw SuperDocs response for error
    messages -- never raises, never dumps something megabytes-large into
    an HTTPException detail string."""
    try:
        text = json.dumps(obj, default=str)
    except Exception:
        text = repr(obj)
    return text if len(text) <= max_len else text[:max_len] + f"...<+{len(text) - max_len} chars>"


@app.on_event("startup")
def on_startup():
    db.init_db()


# -------------------------------------------------------------------------- #
# small shared helpers
# -------------------------------------------------------------------------- #


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _log_event(s: Session, workspace_id: str, event_type: models.ChangeEventType, **kwargs) -> models.ChangeEvent:
    ev = models.ChangeEvent(workspace_id=workspace_id, event_type=event_type, **kwargs)
    s.add(ev)
    s.commit()
    return ev


def _active_sections(s: Session, doc: models.Document) -> list[tuple[models.Section, models.SectionSnapshot]]:
    """Every ACTIVE Section for a document's current active version, paired
    with that version's SectionSnapshot for it, in document order."""
    if not doc.active_version_id:
        return []
    snaps = s.exec(
        select(models.SectionSnapshot)
        .where(models.SectionSnapshot.document_version_id == doc.active_version_id)
        .order_by(models.SectionSnapshot.order_index)
    ).all()
    out = []
    for snap in snaps:
        sec = s.get(models.Section, snap.section_id)
        if sec and sec.status == models.SectionStatus.ACTIVE:
            out.append((sec, snap))
    return out


def _sync_sections_for_version(
    s: Session, doc: models.Document, version: models.DocumentVersion
) -> list[models.Section]:
    """
    Match this version's groups (chunking.group_sections -- a heading chunk
    plus every body chunk up to the next heading, since a real SuperDocs
    parse chunks per element, not per section) back to existing stable
    Section rows for this document -- by ANY previously-known member
    chunk id first (content-only edit, same chunks), then by normalized
    heading text (chunk ids changed but it's recognizably the same
    section) -- create SectionSnapshots (+ their SectionSnapshotChunk
    member rows), create brand-new Sections for headings that match
    nothing, and flag any previously-ACTIVE Section nothing matched this
    round as NEEDS_REANALYSIS rather than guessing at a remap. Returns the
    Sections whose content actually changed vs their previous snapshot
    (empty on the very first version, since there's nothing to diff
    against yet).
    """
    groups = chunking.group_sections(version.normalized_html)

    existing_sections = s.exec(
        select(models.Section).where(
            models.Section.document_id == doc.id, models.Section.status == models.SectionStatus.ACTIVE
        )
    ).all()

    prev_chunk_map: dict[str, models.Section] = {}
    prev_hash_map: dict[str, str] = {}
    for sec in existing_sections:
        last_snap = s.exec(
            select(models.SectionSnapshot)
            .where(models.SectionSnapshot.section_id == sec.id)
            .order_by(models.SectionSnapshot.created_at.desc())
        ).first()
        if last_snap:
            prev_hash_map[sec.id] = last_snap.content_hash
            member_ids = s.exec(
                select(models.SectionSnapshotChunk.chunk_id).where(
                    models.SectionSnapshotChunk.section_snapshot_id == last_snap.id
                )
            ).all()
            for cid in member_ids or [last_snap.chunk_id]:
                prev_chunk_map[cid] = sec

    matched_ids: set[str] = set()
    changed: list[models.Section] = []
    order_index = 0
    display_number = 0

    for group in groups:
        order_index += 1
        heading_text = group["heading_text"]
        member_chunk_ids = group["member_chunk_ids"]
        display_number += 1
        content_hash = chunking.content_hash(group["full_text"])
        content_text = group["full_text"]

        target = None
        for cid in member_chunk_ids:
            target = prev_chunk_map.get(cid)
            if target is not None:
                break
        if target is None:
            normalized_heading = chunking.normalize_text(heading_text)
            for sec in existing_sections:
                if sec.id not in matched_ids and chunking.normalize_text(sec.title) == normalized_heading:
                    target = sec
                    break

        if target is None:
            target = models.Section(
                document_id=doc.id,
                section_number=str(display_number),
                title=heading_text,
                status=models.SectionStatus.ACTIVE,
            )
            s.add(target)
            s.commit()
            s.refresh(target)
        else:
            target.section_number = str(display_number)
            target.title = heading_text
            target.status = models.SectionStatus.ACTIVE
            target.updated_at = _now()
            s.add(target)
            s.commit()

        matched_ids.add(target.id)

        snapshot = models.SectionSnapshot(
            section_id=target.id,
            document_version_id=version.id,
            chunk_id=group["heading_chunk_id"],
            content_html=group["display_html"],
            content_text=content_text,
            content_hash=content_hash,
            order_index=order_index,
        )
        s.add(snapshot)
        s.commit()
        s.refresh(snapshot)

        for cid in member_chunk_ids:
            s.add(models.SectionSnapshotChunk(section_snapshot_id=snapshot.id, chunk_id=cid))
        s.commit()

        prev_hash = prev_hash_map.get(target.id)
        if prev_hash is not None and prev_hash != content_hash:
            changed.append(target)

    for sec in existing_sections:
        if sec.id not in matched_ids:
            sec.status = models.SectionStatus.NEEDS_REANALYSIS
            sec.updated_at = _now()
            s.add(sec)
    s.commit()

    return changed


def _create_document_version(
    s: Session,
    doc: models.Document,
    *,
    normalized_html: str,
    source_format: models.SourceFormat,
    raw_file_bytes: bytes | None = None,
    raw_file_filename: str | None = None,
    raw_file_mime_type: str | None = None,
    superdocs_version_id: str | None = None,
    change_summary: str | None = None,
    created_by: str = "system",
) -> models.DocumentVersion:
    """Archive the current ACTIVE version (if any) and create+activate a new one."""
    prior_active = None
    if doc.active_version_id:
        prior_active = s.get(models.DocumentVersion, doc.active_version_id)

    version_number = 1
    if prior_active:
        version_number = prior_active.version_number + 1

    version = models.DocumentVersion(
        document_id=doc.id,
        version_number=version_number,
        status=models.DocumentVersionStatus.ACTIVE,
        source_format=source_format,
        raw_file_bytes=raw_file_bytes,
        raw_file_filename=raw_file_filename,
        raw_file_mime_type=raw_file_mime_type,
        normalized_html=normalized_html,
        superdocs_version_id=superdocs_version_id,
        change_summary=change_summary,
        created_by=created_by,
    )
    s.add(version)
    s.commit()
    s.refresh(version)

    if prior_active:
        prior_active.status = models.DocumentVersionStatus.ARCHIVED
        s.add(prior_active)

    doc.active_version_id = version.id
    doc.updated_at = _now()
    s.add(doc)
    s.commit()
    s.refresh(version)
    return version


def _upsert_finding(
    s: Session,
    workspace_id: str,
    finding_type: models.FindingType,
    source_section_id: str,
    target_section_id: str | None,
    reference_id: str | None,
    description: str,
    evidence: str | None = None,
) -> models.Finding:
    """Dedup against any already-OPEN finding of the same type/section pair
    rather than creating a fresh row every time validation re-runs."""
    existing = s.exec(
        select(models.Finding).where(
            models.Finding.workspace_id == workspace_id,
            models.Finding.finding_type == finding_type,
            models.Finding.source_section_id == source_section_id,
            models.Finding.target_section_id == target_section_id,
            models.Finding.status == models.FindingStatus.OPEN,
        )
    ).first()
    if existing:
        return existing
    f = models.Finding(
        workspace_id=workspace_id,
        finding_type=finding_type,
        source_section_id=source_section_id,
        target_section_id=target_section_id,
        reference_id=reference_id,
        description=description,
        evidence=evidence,
    )
    s.add(f)
    s.commit()
    s.refresh(f)
    return f


# -------------------------------------------------------------------------- #
# serialization
# -------------------------------------------------------------------------- #


def _workspace_out(w: models.Workspace) -> dict:
    return {
        "id": w.id,
        "organization_name": w.organization_name,
        "organization_type": w.organization_type,
        "pack_name": w.pack_name,
        "status": w.status,
        "created_at": w.created_at,
        "updated_at": w.updated_at,
    }


def _doc_out(d: models.Document) -> dict:
    return {
        "id": d.id,
        "workspace_id": d.workspace_id,
        "doc_type": d.doc_type,
        "parent_policy_id": d.parent_policy_id,
        "title": d.title,
        "superdocs_document_id": d.superdocs_document_id,
        "superdocs_session_id": d.superdocs_session_id,
        "active_version_id": d.active_version_id,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


def _version_out(v: models.DocumentVersion, include_html: bool = False) -> dict:
    out = {
        "id": v.id,
        "document_id": v.document_id,
        "version_number": v.version_number,
        "status": v.status,
        "source_format": v.source_format,
        "raw_file_filename": v.raw_file_filename,
        "superdocs_version_id": v.superdocs_version_id,
        "change_summary": v.change_summary,
        "created_by": v.created_by,
        "created_at": v.created_at,
    }
    if include_html:
        out["normalized_html"] = v.normalized_html
    return out


def _section_out(sec: models.Section, snapshot: models.SectionSnapshot | None = None) -> dict:
    out = {
        "id": sec.id,
        "document_id": sec.document_id,
        "parent_section_id": sec.parent_section_id,
        "section_number": sec.section_number,
        "title": sec.title,
        "level": sec.level,
        "section_type": sec.section_type,
        "status": sec.status,
    }
    if snapshot is not None:
        out["chunk_id"] = snapshot.chunk_id
        out["content_html"] = snapshot.content_html
        out["content_text"] = snapshot.content_text
        out["content_hash"] = snapshot.content_hash
    return out


def _reference_out(r: models.ProcedurePolicyReference, s: Session | None = None) -> dict:
    out = {
        "id": r.id,
        "procedure_section_id": r.procedure_section_id,
        "policy_section_id": r.policy_section_id,
        "relationship_type": r.relationship_type,
        "confidence": r.confidence,
        "evidence": r.evidence,
        "status": r.status,
        "source": r.source,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }
    if s is not None:
        psec = s.get(models.Section, r.policy_section_id)
        procsec = s.get(models.Section, r.procedure_section_id)
        if psec:
            out["policy_section"] = _section_out(psec)
            out["policy_document_id"] = psec.document_id
        if procsec:
            out["procedure_section"] = _section_out(procsec)
            out["procedure_document_id"] = procsec.document_id
    return out


def _finding_out(f: models.Finding) -> dict:
    return {
        "id": f.id,
        "finding_type": f.finding_type,
        "source_section_id": f.source_section_id,
        "target_section_id": f.target_section_id,
        "reference_id": f.reference_id,
        "description": f.description,
        "evidence": f.evidence,
        "status": f.status,
        "created_at": f.created_at,
        "resolved_at": f.resolved_at,
    }


def _proposed_change_out(pc: models.ProposedChange) -> dict:
    return {
        "id": pc.id,
        "update_request_id": pc.update_request_id,
        "document_id": pc.document_id,
        "section_id": pc.section_id,
        "base_version_id": pc.base_version_id,
        "reference_id": pc.reference_id,
        "superdocs_job_id": pc.superdocs_job_id,
        "old_html": pc.old_html,
        "new_html": pc.new_html,
        "ai_explanation": pc.ai_explanation,
        "status": pc.status,
        "reviewed_by": pc.reviewed_by,
        "reviewed_at": pc.reviewed_at,
        "feedback": pc.feedback,
        "resulting_version_id": pc.resulting_version_id,
        "created_at": pc.created_at,
    }


def _event_out(ev: models.ChangeEvent) -> dict:
    return {
        "id": ev.id,
        "event_type": ev.event_type,
        "timestamp": ev.timestamp,
        "document_id": ev.document_id,
        "document_version_id": ev.document_version_id,
        "section_id": ev.section_id,
        "reference_id": ev.reference_id,
        "update_request_id": ev.update_request_id,
        "proposed_change_id": ev.proposed_change_id,
        "actor": ev.actor,
        "description": ev.description,
        "approved": ev.approved,
    }


# ============================================================================
# 1. workspaces
# ============================================================================


class WorkspaceCreate(BaseModel):
    organization_name: str
    organization_type: str | None = None
    pack_name: str


@app.post("/workspaces")
def create_workspace(req: WorkspaceCreate):
    with Session(db.get_engine()) as s:
        ws = models.Workspace(
            organization_name=req.organization_name,
            organization_type=req.organization_type,
            pack_name=req.pack_name,
        )
        s.add(ws)
        s.commit()
        s.refresh(ws)
        _log_event(
            s, ws.id, models.ChangeEventType.WORKSPACE_CREATED,
            actor="human", description=f"Workspace {ws.pack_name!r} created for {ws.organization_name!r}",
        )
        return _workspace_out(ws)


@app.get("/workspaces")
def list_workspaces():
    with Session(db.get_engine()) as s:
        return [_workspace_out(w) for w in s.exec(select(models.Workspace)).all()]


@app.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str):
    with Session(db.get_engine()) as s:
        ws = s.get(models.Workspace, workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")
        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()
        out = _workspace_out(ws)
        out["policies"] = sum(1 for d in docs if d.doc_type == models.DocType.POLICY)
        out["procedures"] = sum(1 for d in docs if d.doc_type == models.DocType.PROCEDURE)
        return out


# ============================================================================
# 2-4. documents: upload/grouping, list, detail
# ============================================================================


class DocumentUploadRequest(BaseModel):
    filename: str
    file_base64: str
    doc_type: str  # "policy" | "procedure"
    title: str
    parent_policy_id: str | None = None  # required for doc_type == "procedure"


@app.post("/workspaces/{workspace_id}/documents/upload")
def upload_document(workspace_id: str, req: DocumentUploadRequest):
    """
    The only ingestion path. A human picks a file, a type, a title, and --
    for procedures -- which policy it's grouped under (document-level
    grouping only; SECTION-level references come later, from Analyze
    References, not from anything chosen here). Nothing is uploaded
    automatically anywhere else in this codebase.
    """
    if req.doc_type not in ("policy", "procedure"):
        raise HTTPException(400, "doc_type must be 'policy' or 'procedure'")

    client = get_client()
    with Session(db.get_engine()) as s:
        ws = s.get(models.Workspace, workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")

        parent_policy: models.Document | None = None
        if req.doc_type == "procedure":
            if not req.parent_policy_id:
                raise HTTPException(400, "procedure uploads must specify parent_policy_id")
            parent_policy = s.get(models.Document, req.parent_policy_id)
            if parent_policy is None or parent_policy.doc_type != models.DocType.POLICY:
                raise HTTPException(404, "parent_policy_id does not refer to a policy document")

        try:
            raw_bytes = base64.b64decode(req.file_base64)
        except Exception:
            raise HTTPException(400, "file_base64 is not valid base64")

        ext = req.filename.rsplit(".", 1)[-1].lower() if "." in req.filename else ""
        source_format = _SOURCE_FORMAT_BY_EXT.get(ext, models.SourceFormat.TXT)

        session_id = f"ws-{workspace_id}-{uuid4()}"
        try:
            upload_resp = client.upload_document_base64(
                filename=req.filename,
                html_or_bytes=raw_bytes,
                session_id=session_id,
                return_html=False,
                is_html_text=False,
            )
            roster = client.list_session_documents(session_id)
            if not roster.get("documents"):
                raise HTTPException(
                    502,
                    f"upload succeeded but the session roster came back empty. "
                    f"debug: upload_resp={_safe_debug(upload_resp)}, roster={_safe_debug(roster)}",
                )
            durable_id = roster["documents"][0]["durable_document_id"]
            detail = client.get_document(durable_id, include_html=True)
        except SuperDocsError as e:
            raise HTTPException(502, f"upload failed: {e}")

        persisted_html = detail.get("html") or ""
        chunks = chunking.extract_chunks(persisted_html)
        if not chunks:
            # Should now only trip on a genuinely empty/unparseable document --
            # extract_chunks() recognizes data-chunk-id on ANY element (p, h1-h6,
            # table, etc, not just div; see chunking.py's _TopLevelChunkSplitter),
            # matching how SuperDocs actually chunks a real parsed .docx/.pdf/etc
            # (confirmed against a live response: chunk ids land on <p>/<h*>/<table>
            # directly, one per paragraph/heading/table, not on an artificial
            # wrapper div). Kept as a diagnostic 502 rather than silently
            # swallowing the failure, since this project's dependency model
            # requires SuperDocs' own chunk ids to exist at all for a document to
            # be addressable.
            structure = detail.get("structure") or {}
            raise HTTPException(
                502,
                "SuperDocs returned a document with no addressable chunk-id "
                "elements at all in its HTML. debug: "
                f"detail_keys={sorted(detail.keys())}, "
                f"html_len={len(persisted_html)}, "
                f"html_head={persisted_html[:300]!r}, "
                f"structure_headings={structure.get('headings')}, "
                f"structure_block_count={structure.get('block_count')}, "
                f"upload_resp={_safe_debug(upload_resp)}, "
                f"roster_doc_keys={sorted(roster['documents'][0].keys())}",
            )

        doc = models.Document(
            workspace_id=workspace_id,
            doc_type=models.DocType.POLICY if req.doc_type == "policy" else models.DocType.PROCEDURE,
            parent_policy_id=parent_policy.id if parent_policy else None,
            title=req.title,
            superdocs_document_id=durable_id,
            superdocs_session_id=session_id,
        )
        s.add(doc)
        s.commit()
        s.refresh(doc)

        version = _create_document_version(
            s,
            doc,
            normalized_html=persisted_html,
            source_format=source_format,
            raw_file_bytes=raw_bytes,
            raw_file_filename=req.filename,
            raw_file_mime_type=None,
            superdocs_version_id=upload_resp.get("version_id"),
            change_summary="Initial upload",
            created_by="human:uploaded",
        )
        changed = _sync_sections_for_version(s, doc, version)  # empty on first version, by design
        sections = _active_sections(s, doc)

        if not sections:
            raise HTTPException(
                502,
                "No sections could be discovered from this document's headings. Make sure the "
                "document uses heading styles (H1/H2/etc.) for each section title.",
            )

        _log_event(
            s, workspace_id, models.ChangeEventType.DOCUMENT_UPLOADED,
            document_id=doc.id, document_version_id=version.id,
            actor="human:uploaded",
            description=f"Uploaded {req.filename!r} as {req.doc_type} document {doc.title!r} "
                        f"({len(sections)} sections discovered)",
        )

        return {
            "document": _doc_out(doc),
            "version": _version_out(version),
            "sections": [_section_out(sec, snap) for sec, snap in sections],
        }


class DocumentDraftRequest(BaseModel):
    doc_type: str  # "policy" | "procedure"
    title: str
    prompt: str  # e.g. "Draft a Data Breach Notification policy for a mid-size clinic"
    parent_policy_id: str | None = None  # required for doc_type == "procedure"


@app.post("/workspaces/{workspace_id}/documents/draft")
def draft_document(workspace_id: str, req: DocumentDraftRequest):
    """
    The templates surface, exercised for real: ensure our structural
    templates are uploaded, then ask SuperDocs to draft a brand-new
    document from scratch (POST /v1/chat with no document_html -- the AI
    searches the account's uploaded templates and uses one as a starting
    point, per docs.superdocs.app/concepts/templates). This is a second,
    parallel document-creation path alongside upload_document -- a human
    still picks doc_type/title/(parent policy), but instead of supplying a
    file, they supply an instruction and the AI + a template produce the
    starting content, which then flows through the exact same
    version/section/reference machinery as an uploaded document.
    """
    if req.doc_type not in ("policy", "procedure"):
        raise HTTPException(400, "doc_type must be 'policy' or 'procedure'")
    if not req.prompt.strip():
        raise HTTPException(400, "prompt is required")

    client = get_client()
    with Session(db.get_engine()) as s:
        ws = s.get(models.Workspace, workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")

        parent_policy: models.Document | None = None
        if req.doc_type == "procedure":
            if not req.parent_policy_id:
                raise HTTPException(400, "procedure drafts must specify parent_policy_id")
            parent_policy = s.get(models.Document, req.parent_policy_id)
            if parent_policy is None or parent_policy.doc_type != models.DocType.POLICY:
                raise HTTPException(404, "parent_policy_id does not refer to a policy document")

        session_id = f"ws-{workspace_id}-draft-{uuid4()}"
        try:
            _ensure_templates_uploaded(client)
            client.chat(session_id=session_id, message=req.prompt)
            roster = client.list_session_documents(session_id)
            if not roster.get("documents"):
                raise HTTPException(
                    502,
                    f"draft succeeded but the session roster came back empty. "
                    f"debug: roster={_safe_debug(roster)}",
                )
            durable_id = roster["documents"][0]["durable_document_id"]
            detail = client.get_document(durable_id, include_html=True)
        except SuperDocsError as e:
            raise HTTPException(502, f"draft failed: {e}")

        persisted_html = detail.get("html") or ""
        chunks = chunking.extract_chunks(persisted_html)
        if not chunks:
            raise HTTPException(
                502,
                "SuperDocs drafted a document with no addressable chunk-id elements. "
                f"debug: html_len={len(persisted_html)}, html_head={persisted_html[:300]!r}",
            )

        doc = models.Document(
            workspace_id=workspace_id,
            doc_type=models.DocType.POLICY if req.doc_type == "policy" else models.DocType.PROCEDURE,
            parent_policy_id=parent_policy.id if parent_policy else None,
            title=req.title,
            superdocs_document_id=durable_id,
            superdocs_session_id=session_id,
        )
        s.add(doc)
        s.commit()
        s.refresh(doc)

        # Stored as a real HTML "file" (raw_file_bytes populated), same as
        # any other version 1 -- see DocumentVersion's docstring: v1 always
        # carries the literal bytes of what became the document, whether a
        # human uploaded them or the AI drafted them from a template.
        raw_html_bytes = persisted_html.encode("utf-8")
        version = _create_document_version(
            s,
            doc,
            normalized_html=persisted_html,
            source_format=models.SourceFormat.HTML,
            raw_file_bytes=raw_html_bytes,
            raw_file_filename=f"{req.title}.html",
            raw_file_mime_type="text/html",
            change_summary=f"AI draft from template: {req.prompt[:100]}",
            created_by="ai:template-draft",
        )
        _sync_sections_for_version(s, doc, version)
        sections = _active_sections(s, doc)

        if not sections:
            raise HTTPException(
                502,
                "No sections could be discovered from the drafted document. The AI's draft may not "
                "have used heading styles (H1/H2/etc.) -- try a more specific prompt.",
            )

        _log_event(
            s, workspace_id, models.ChangeEventType.DOCUMENT_DRAFTED,
            document_id=doc.id, document_version_id=version.id,
            actor="ai:template-draft",
            description=f"Drafted {req.doc_type} document {doc.title!r} from prompt "
                        f"{req.prompt[:80]!r} ({len(sections)} sections discovered)",
        )

        return {
            "document": _doc_out(doc),
            "version": _version_out(version),
            "sections": [_section_out(sec, snap) for sec, snap in sections],
        }


@app.get("/workspaces/{workspace_id}/documents")
def list_workspace_documents(workspace_id: str):
    with Session(db.get_engine()) as s:
        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()
        return [_doc_out(d) for d in docs]


@app.get("/documents/{document_id}")
def get_document(document_id: str, include_html: bool = False):
    with Session(db.get_engine()) as s:
        doc = s.get(models.Document, document_id)
        if doc is None:
            raise HTTPException(404, "document not found")
        out = _doc_out(doc)
        sections = _active_sections(s, doc)
        out["sections"] = [_section_out(sec, snap) for sec, snap in sections]
        if include_html and doc.active_version_id:
            version = s.get(models.DocumentVersion, doc.active_version_id)
            out["html"] = version.normalized_html if version else None
        return out


def _delete_document_cascade(s: Session, doc: models.Document) -> dict:
    """
    Hard-deletes a Document and everything that only exists because of it
    (versions, sections, snapshots, the reference-graph edges touching its
    sections, proposed changes, findings, validation-check rows, update
    requests). Nothing outside this document's own subtree is deleted --
    ChangeEvent rows are kept (per the append-only audit-log design in
    models.py) with their FK columns into the deleted rows simply nulled
    out, so "what happened and when" survives even though the thing it
    happened to no longer does.

    Deliberately does NOT touch SuperDocs itself -- there is no
    delete-document capability on SuperDocsClient (only delete_template),
    so the underlying SuperDocs document/session is left as-is; this only
    removes the document from this app's own workspace view.

    Caller is responsible for the workspace-level guard (blocking deletion
    of a policy that still has linked procedures) before calling this.
    """
    version_ids = [
        v.id for v in s.exec(select(models.DocumentVersion).where(models.DocumentVersion.document_id == doc.id)).all()
    ]
    section_ids = [
        sec.id for sec in s.exec(select(models.Section).where(models.Section.document_id == doc.id)).all()
    ]

    snapshot_ids: list[str] = []
    if version_ids or section_ids:
        snap_q = select(models.SectionSnapshot)
        snaps = s.exec(snap_q).all()
        snapshot_ids = [
            snap.id for snap in snaps
            if snap.document_version_id in version_ids or snap.section_id in section_ids
        ]

    reference_ids: list[str] = []
    if section_ids or snapshot_ids:
        refs = s.exec(select(models.ProcedurePolicyReference)).all()
        reference_ids = [
            r.id for r in refs
            if r.procedure_section_id in section_ids
            or r.policy_section_id in section_ids
            or r.policy_section_snapshot_id in snapshot_ids
            or r.procedure_section_snapshot_id in snapshot_ids
        ]

    proposed_change_ids: list[str] = []
    all_pcs = s.exec(select(models.ProposedChange)).all()
    proposed_change_ids = [
        pc.id for pc in all_pcs
        if pc.document_id == doc.id
        or pc.section_id in section_ids
        or pc.reference_id in reference_ids
        or pc.base_version_id in version_ids
        or pc.resulting_version_id in version_ids
    ]

    update_request_ids = [
        ur.id for ur in s.exec(select(models.UpdateRequest).where(models.UpdateRequest.document_id == doc.id)).all()
    ]

    # 1. chunks under the snapshots being removed
    if snapshot_ids:
        for chunk in s.exec(
            select(models.SectionSnapshotChunk).where(models.SectionSnapshotChunk.section_snapshot_id.in_(snapshot_ids))
        ).all():
            s.delete(chunk)

    # 2. transient per-run validation rows that point at what we're removing
    if reference_ids or section_ids:
        for vcr in s.exec(select(models.ValidationCheckResult)).all():
            if vcr.reference_id in reference_ids or vcr.section_id in section_ids:
                s.delete(vcr)

    # 3. findings about sections/references that won't exist anymore
    deleted_finding_ids: list[str] = []
    if section_ids or reference_ids:
        for f in s.exec(select(models.Finding)).all():
            if f.source_section_id in section_ids or f.target_section_id in section_ids or f.reference_id in reference_ids:
                deleted_finding_ids.append(f.id)
                s.delete(f)

    # 4. surviving findings that pointed at a proposed change we're about to delete
    if proposed_change_ids:
        for f in s.exec(select(models.Finding)).all():
            if f.resolved_by_change_id in proposed_change_ids:
                f.resolved_by_change_id = None
                s.add(f)

    # 5. keep the audit log rows, just null out the FKs into things we delete
    touched_change_events = s.exec(select(models.ChangeEvent)).all()
    for ev in touched_change_events:
        dirty = False
        if ev.document_id == doc.id:
            ev.document_id = None
            dirty = True
        if ev.document_version_id in version_ids:
            ev.document_version_id = None
            dirty = True
        if ev.section_id in section_ids:
            ev.section_id = None
            dirty = True
        if ev.reference_id in reference_ids:
            ev.reference_id = None
            dirty = True
        if ev.update_request_id in update_request_ids:
            ev.update_request_id = None
            dirty = True
        if ev.proposed_change_id in proposed_change_ids:
            ev.proposed_change_id = None
            dirty = True
        if dirty:
            s.add(ev)

    # 6. proposed changes (this document's own edits + anything propagated
    #    off a reference that's about to disappear)
    for pc_id in proposed_change_ids:
        pc = s.get(models.ProposedChange, pc_id)
        if pc is not None:
            s.delete(pc)

    # 7. the reference-graph edges touching this document's sections
    for ref_id in reference_ids:
        ref = s.get(models.ProcedurePolicyReference, ref_id)
        if ref is not None:
            s.delete(ref)

    # 8. update requests raised against this document
    for ur_id in update_request_ids:
        ur = s.get(models.UpdateRequest, ur_id)
        if ur is not None:
            s.delete(ur)

    # 9. detach the document's own active-version pointer before the
    #    versions it points at get deleted
    doc.active_version_id = None
    s.add(doc)
    s.commit()

    # 10. section snapshots
    for snap_id in snapshot_ids:
        snap = s.get(models.SectionSnapshot, snap_id)
        if snap is not None:
            s.delete(snap)

    # 11. resolved split/merge lineage rows for this document's sections
    if section_ids:
        for rel in s.exec(select(models.SectionRelation)).all():
            if rel.source_section_id in section_ids or rel.target_section_id in section_ids:
                s.delete(rel)

    # 12. sections themselves
    for sec_id in section_ids:
        sec = s.get(models.Section, sec_id)
        if sec is not None:
            s.delete(sec)

    # 13. analysis jobs that paired this document with another
    for job in s.exec(
        select(models.AnalysisJob).where(
            (models.AnalysisJob.policy_document_id == doc.id) | (models.AnalysisJob.procedure_document_id == doc.id)
        )
    ).all():
        s.delete(job)

    # 14. document versions
    for v_id in version_ids:
        v = s.get(models.DocumentVersion, v_id)
        if v is not None:
            s.delete(v)

    # None of Section/DocumentVersion/AnalysisJob declare an ORM
    # Relationship() back to Document (every FK in this schema is a plain
    # column, not a relationship -- see models.py), so SQLAlchemy has no
    # dependency info to auto-order their deletes against the document's
    # own delete when both are queued in the same flush, and can emit
    # DELETE FROM document first -- a real FK violation on Postgres.
    # Flushing here forces steps 10-14 to hit the DB before the document
    # delete below is even queued.
    s.flush()

    # 15. the document itself
    doc_id, doc_title, doc_type = doc.id, doc.title, doc.doc_type
    s.delete(doc)
    s.commit()

    return {
        "deleted_document_id": doc_id,
        "deleted_document_title": doc_title,
        "deleted_document_type": doc_type,
        "deleted_sections": len(section_ids),
        "deleted_references": len(reference_ids),
        "deleted_proposed_changes": len(proposed_change_ids),
        "deleted_findings": len(deleted_finding_ids),
        "deleted_versions": len(version_ids),
    }


@app.delete("/documents/{document_id}")
def delete_document(document_id: str):
    """
    Permanently removes a policy or procedure and everything that only
    existed because of it. A policy with procedures still grouped under it
    can't be deleted directly -- delete or reassign those procedures first,
    so one click can't silently wipe out several documents at once.
    """
    with Session(db.get_engine()) as s:
        doc = s.get(models.Document, document_id)
        if doc is None:
            raise HTTPException(404, "document not found")

        if doc.doc_type == models.DocType.POLICY:
            linked = s.exec(
                select(models.Document).where(models.Document.parent_policy_id == document_id)
            ).all()
            if linked:
                names = ", ".join(p.title for p in linked)
                raise HTTPException(
                    400,
                    f"This policy still has {len(linked)} procedure(s) grouped under it ({names}). "
                    f"Delete those procedures first, then delete the policy.",
                )

        workspace_id = doc.workspace_id
        result = _delete_document_cascade(s, doc)

        _log_event(
            s, workspace_id, models.ChangeEventType.DOCUMENT_DELETED,
            actor="human:deleted",
            description=f"Deleted {result['deleted_document_type']} document {result['deleted_document_title']!r} "
                        f"({result['deleted_sections']} sections, {result['deleted_references']} references, "
                        f"{result['deleted_proposed_changes']} proposed changes removed with it)",
        )

        return result


@app.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: str):
    """
    Permanently deletes an entire compliance workspace: every document
    (reusing _delete_document_cascade() per document, via delete_document()
    above, so versions/sections/snapshots/references/proposed changes/
    findings/update requests are all removed exactly the same way a
    single-document delete removes them) plus everything left at the
    workspace level once no document remains to anchor it -- analysis runs,
    validation runs (and their check-result rows), reports, export records,
    and the change-log itself. Irreversible.

    Deletes every PROCEDURE before any POLICY: delete_document() refuses to
    delete a policy that still has procedures grouped under it (a guard
    that exists for the single-document delete UX, and stays correct here
    too -- it just means a full wipe has to respect the same order).

    ExportRecord.report_id is a foreign key into Report, so export records
    are removed before reports. None of the tables in models.py declare an
    ORM Relationship() back to Workspace (every workspace_id here is a
    plain FK column, not a relationship) -- unlike a table that does have
    one, SQLAlchemy has no dependency info to auto-order these deletes, so
    every step below is explicit and flushed before the workspace row
    itself is queued for deletion.
    """
    with Session(db.get_engine()) as s:
        ws = s.get(models.Workspace, workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")
        workspace_name = ws.organization_name

        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()
        procedure_ids = [d.id for d in docs if d.doc_type == models.DocType.PROCEDURE]
        policy_ids = [d.id for d in docs if d.doc_type == models.DocType.POLICY]

    # delete_document() opens and commits its own Session per call (same as
    # calling the real DELETE /documents/{id} endpoint once per document).
    for doc_id in procedure_ids:
        delete_document(doc_id)
    for doc_id in policy_ids:
        delete_document(doc_id)

    with Session(db.get_engine()) as s:
        # Each layer below is flushed before the next starts. None of these
        # tables declare an ORM Relationship() to their parent (every FK in
        # this schema -- AnalysisJob.run_id, ValidationCheckResult.
        # validation_run_id, ExportRecord.report_id -- is a plain column,
        # not a relationship), so within a single flush SQLAlchemy has no
        # dependency info and can emit the parent's DELETE before the
        # child's, hitting a real FK violation on Postgres (and, once
        # autoflush fires on the next query in this same function, even
        # against SQLite with foreign_keys=ON). Explicit flushes make the
        # child rows hit the DB before their parent is even queued.
        run_ids = [r.id for r in s.exec(select(models.AnalysisRun).where(models.AnalysisRun.workspace_id == workspace_id)).all()]
        if run_ids:
            for job in s.exec(select(models.AnalysisJob).where(models.AnalysisJob.run_id.in_(run_ids))).all():
                s.delete(job)
            s.flush()
        for run in s.exec(select(models.AnalysisRun).where(models.AnalysisRun.workspace_id == workspace_id)).all():
            s.delete(run)
        s.flush()

        # ExportRecord.report_id and Report.validation_run_id are both
        # foreign keys (into Report and ValidationRun respectively), so
        # exports are removed before reports, and reports before
        # validation runs -- Report sits in the *middle* of that chain, not
        # at either end.
        for exp in s.exec(select(models.ExportRecord).where(models.ExportRecord.workspace_id == workspace_id)).all():
            s.delete(exp)
        s.flush()

        for rep in s.exec(select(models.Report).where(models.Report.workspace_id == workspace_id)).all():
            s.delete(rep)
        s.flush()

        vr_ids = [v.id for v in s.exec(select(models.ValidationRun).where(models.ValidationRun.workspace_id == workspace_id)).all()]
        if vr_ids:
            for vcr in s.exec(select(models.ValidationCheckResult).where(models.ValidationCheckResult.validation_run_id.in_(vr_ids))).all():
                s.delete(vcr)
            s.flush()
        for vr in s.exec(select(models.ValidationRun).where(models.ValidationRun.workspace_id == workspace_id)).all():
            s.delete(vr)
        s.flush()

        for ev in s.exec(select(models.ChangeEvent).where(models.ChangeEvent.workspace_id == workspace_id)).all():
            s.delete(ev)
        s.flush()

        ws = s.get(models.Workspace, workspace_id)
        s.delete(ws)
        s.commit()

    return {
        "status": "deleted",
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "deleted_documents": len(procedure_ids) + len(policy_ids),
    }


# ============================================================================
# 5-6. analyze references
# ============================================================================


@app.post("/workspaces/{workspace_id}/analyze")
def analyze_references(workspace_id: str, max_concurrency: int = DEFAULT_ANALYSIS_CONCURRENCY):
    """
    Creates one AnalysisJob per (policy, procedure) pair already grouped
    together (via parent_policy_id, established at upload time with zero
    AI), runs them under a concurrency-limited thread pool, and writes
    confidence-gated ProcedurePolicyReference rows. This is the only phase
    of the system that calls an LLM directly rather than SuperDocs -- see
    llm_client.py for why.
    """
    with Session(db.get_engine()) as s:
        ws = s.get(models.Workspace, workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")

        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()
        policies = {d.id: d for d in docs if d.doc_type == models.DocType.POLICY}
        procedures = [d for d in docs if d.doc_type == models.DocType.PROCEDURE]
        pairs = [(policies[p.parent_policy_id], p) for p in procedures if p.parent_policy_id in policies]

        if not pairs:
            raise HTTPException(
                400,
                "no policy/procedure pairs to analyze -- upload documents and group each "
                "procedure under a policy first",
            )

        run = models.AnalysisRun(workspace_id=workspace_id, status=models.AnalysisRunStatus.PROCESSING)
        s.add(run)
        s.commit()
        s.refresh(run)
        run_id = run.id

        job_ids = []
        for policy_doc, proc_doc in pairs:
            job = models.AnalysisJob(
                run_id=run_id, policy_document_id=policy_doc.id, procedure_document_id=proc_doc.id
            )
            s.add(job)
            s.commit()
            s.refresh(job)
            job_ids.append(job.id)

        ws.status = models.WorkspaceStatus.ANALYZING
        s.add(ws)
        s.commit()
        _log_event(
            s, workspace_id, models.ChangeEventType.ANALYSIS_RUN_STARTED,
            actor="human", description=f"Analyze References started: {len(job_ids)} policy/procedure pairs",
        )

    llm = get_llm_client()

    def run_job(job_id: str) -> None:
        with Session(db.get_engine()) as s2:
            job = s2.get(models.AnalysisJob, job_id)
            job.status = models.AnalysisJobStatus.RUNNING
            job.started_at = _now()
            s2.add(job)
            s2.commit()

            try:
                policy_doc = s2.get(models.Document, job.policy_document_id)
                proc_doc = s2.get(models.Document, job.procedure_document_id)
                policy_sections = _active_sections(s2, policy_doc)
                proc_sections = _active_sections(s2, proc_doc)
                if not policy_sections or not proc_sections:
                    raise RuntimeError("policy or procedure has no active sections to analyze")

                policy_snap_by_section = {sec.id: snap for sec, snap in policy_sections}
                proc_snap_by_section = {sec.id: snap for sec, snap in proc_sections}

                result = llm.discover_references(
                    policy_title=policy_doc.title,
                    policy_sections=[
                        llm_client.SectionInput(id=sec.id, number=sec.section_number, title=sec.title, content_text=snap.content_text)
                        for sec, snap in policy_sections
                    ],
                    procedure_title=proc_doc.title,
                    procedure_sections=[
                        llm_client.SectionInput(id=sec.id, number=sec.section_number, title=sec.title, content_text=snap.content_text)
                        for sec, snap in proc_sections
                    ],
                )

                created = 0
                for rel in result.relationships:
                    if rel.confidence < CONFIDENCE_MIN:
                        continue
                    policy_snap = policy_snap_by_section.get(rel.policy_section_id)
                    proc_snap = proc_snap_by_section.get(rel.procedure_section_id)
                    if policy_snap is None or proc_snap is None:
                        continue  # model echoed an id we never gave it -- skip rather than guess
                    status = (
                        models.ReferenceStatus.VALID
                        if rel.confidence >= CONFIDENCE_AUTO_ACCEPT
                        else models.ReferenceStatus.NEEDS_REVIEW
                    )
                    ref = models.ProcedurePolicyReference(
                        procedure_section_id=rel.procedure_section_id,
                        policy_section_id=rel.policy_section_id,
                        confidence=rel.confidence,
                        evidence=rel.reason,
                        status=status,
                        source=models.ReferenceSource.LLM_ANALYSIS,
                        analysis_job_id=job.id,
                        policy_section_snapshot_id=policy_snap.id,
                        procedure_section_snapshot_id=proc_snap.id,
                    )
                    s2.add(ref)
                    created += 1
                s2.commit()

                job.status = models.AnalysisJobStatus.COMPLETE
                job.llm_model = result.usage.model
                job.llm_input_tokens = result.usage.input_tokens
                job.llm_output_tokens = result.usage.output_tokens
            except Exception as e:  # noqa: BLE001 -- job-level failure isolation, one bad pair shouldn't kill the run
                job.status = models.AnalysisJobStatus.FAILED
                job.error_message = str(e)

            job.completed_at = _now()
            s2.add(job)
            s2.commit()

    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        list(pool.map(run_job, job_ids))

    with Session(db.get_engine()) as s:
        run = s.get(models.AnalysisRun, run_id)
        run.status = models.AnalysisRunStatus.COMPLETE
        run.completed_at = _now()
        s.add(run)

        jobs = s.exec(select(models.AnalysisJob).where(models.AnalysisJob.run_id == run_id)).all()
        any_needs_review = s.exec(
            select(models.ProcedurePolicyReference).where(
                models.ProcedurePolicyReference.analysis_job_id.in_([j.id for j in jobs]),
                models.ProcedurePolicyReference.status == models.ReferenceStatus.NEEDS_REVIEW,
            )
        ).first()
        any_failed = any(j.status == models.AnalysisJobStatus.FAILED for j in jobs)

        ws = s.get(models.Workspace, workspace_id)
        ws.status = models.WorkspaceStatus.NEEDS_ATTENTION if (any_needs_review or any_failed) else models.WorkspaceStatus.READY
        s.add(ws)
        s.commit()

        _log_event(
            s, workspace_id, models.ChangeEventType.ANALYSIS_RUN_COMPLETED,
            actor="system",
            description=f"Analyze References completed: {sum(1 for j in jobs if j.status == models.AnalysisJobStatus.COMPLETE)}/{len(jobs)} pairs succeeded",
        )

        return {
            "run_id": run_id,
            "jobs": [
                {
                    "id": j.id,
                    "policy_document_id": j.policy_document_id,
                    "procedure_document_id": j.procedure_document_id,
                    "status": j.status,
                    "error_message": j.error_message,
                }
                for j in jobs
            ],
            "workspace_status": ws.status,
        }


@app.get("/workspaces/{workspace_id}/references")
def list_references(workspace_id: str):
    with Session(db.get_engine()) as s:
        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()
        doc_ids = {d.id for d in docs}
        sections = s.exec(select(models.Section).where(models.Section.document_id.in_(doc_ids))).all()
        section_ids = {sec.id for sec in sections}
        refs = s.exec(
            select(models.ProcedurePolicyReference).where(
                models.ProcedurePolicyReference.procedure_section_id.in_(section_ids)
            )
        ).all()
        return [_reference_out(r, s) for r in refs]


# ============================================================================
# 7-8. validate + findings
# ============================================================================

_NUMBER_UNIT_RE = re.compile(
    r"\b(\d+)\s*(hour|hours|hr|hrs|day|days|business day|business days|week|weeks|month|months|year|years)\b",
    re.IGNORECASE,
)


def _number_unit_phrases(text: str) -> set[str]:
    return {f"{n} {u.lower()}" for n, u in _NUMBER_UNIT_RE.findall(text)}


@app.post("/workspaces/{workspace_id}/validate")
def validate_workspace(workspace_id: str):
    """
    Independent re-check, entirely against our own persisted data -- no
    SuperDocs calls needed, because (unlike the old build) every section's
    full content already lives in Postgres. Writes a ValidationRun +
    ValidationCheckResult per check, and upserts a Finding for anything
    that fails so problems persist as a worklist rather than only existing
    inside this run's report.
    """
    with Session(db.get_engine()) as s:
        ws = s.get(models.Workspace, workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")

        run = models.ValidationRun(workspace_id=workspace_id)
        s.add(run)
        s.commit()
        s.refresh(run)

        checks: list[models.ValidationCheckResult] = []

        def record(check_type, reference_id, section_id, passed, details):
            checks.append(
                models.ValidationCheckResult(
                    validation_run_id=run.id, check_type=check_type,
                    reference_id=reference_id, section_id=section_id, passed=passed, details=details,
                )
            )

        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()
        procedures = [d for d in docs if d.doc_type == models.DocType.PROCEDURE]
        doc_ids = {d.id for d in docs}
        sections = s.exec(select(models.Section).where(models.Section.document_id.in_(doc_ids))).all()
        section_ids = {sec.id for sec in sections}
        references = s.exec(
            select(models.ProcedurePolicyReference).where(
                models.ProcedurePolicyReference.procedure_section_id.in_(section_ids)
            )
        ).all()
        refs_by_proc_doc: dict[str, list[models.ProcedurePolicyReference]] = {}
        for r in references:
            psec = s.get(models.Section, r.procedure_section_id)
            if psec:
                refs_by_proc_doc.setdefault(psec.document_id, []).append(r)

        # 1. HAS_PARENT_POLICY
        for proc in procedures:
            passed = proc.parent_policy_id is not None
            record(models.ValidationCheckType.HAS_PARENT_POLICY, None, None, passed,
                   f"{proc.title!r} {'has' if passed else 'is missing'} a parent policy")
            if not passed:
                _upsert_finding(
                    s, workspace_id, models.FindingType.MISSING_REFERENCE,
                    source_section_id=next((sec.id for sec in sections if sec.document_id == proc.id), proc.id),
                    target_section_id=None, reference_id=None,
                    description=f"{proc.title!r} is not grouped under any policy.",
                )

        # 2. MISSING_REFERENCE -- procedure has zero section-level references
        for proc in procedures:
            has_refs = bool(refs_by_proc_doc.get(proc.id))
            passed = has_refs
            record(models.ValidationCheckType.MISSING_REFERENCE, None, None, passed,
                   f"{proc.title!r} has {'at least one' if has_refs else 'no'} policy-section reference")
            if not passed and proc.active_version_id:
                proc_sections = _active_sections(s, proc)
                if proc_sections:
                    _upsert_finding(
                        s, workspace_id, models.FindingType.MISSING_REFERENCE,
                        source_section_id=proc_sections[0][0].id, target_section_id=None, reference_id=None,
                        description=f"{proc.title!r} has no policy-section reference at all.",
                    )

        # 3. SECTION_EXISTS + 4. HASH_MATCH + 5. LOW_CONFIDENCE_UNREVIEWED, per reference
        for r in references:
            psec = s.get(models.Section, r.policy_section_id)
            procsec = s.get(models.Section, r.procedure_section_id)
            sections_ok = bool(psec and procsec and psec.status == models.SectionStatus.ACTIVE and procsec.status == models.SectionStatus.ACTIVE)
            record(models.ValidationCheckType.SECTION_EXISTS, r.id, None, sections_ok,
                   "both sections resolve and are active" if sections_ok else "a referenced section is missing or NEEDS_REANALYSIS")
            if not sections_ok:
                _upsert_finding(
                    s, workspace_id, models.FindingType.BROKEN_REFERENCE,
                    source_section_id=r.procedure_section_id, target_section_id=r.policy_section_id, reference_id=r.id,
                    description="This reference points at a section that no longer resolves cleanly (likely restructured).",
                )
                continue

            policy_snap = s.get(models.SectionSnapshot, r.policy_section_snapshot_id)
            proc_snap = s.get(models.SectionSnapshot, r.procedure_section_snapshot_id)
            _, current_policy_snap = next(((sec, snap) for sec, snap in _active_sections(s, s.get(models.Document, psec.document_id)) if sec.id == psec.id), (None, None))
            _, current_proc_snap = next(((sec, snap) for sec, snap in _active_sections(s, s.get(models.Document, procsec.document_id)) if sec.id == procsec.id), (None, None))

            hash_ok = (
                current_policy_snap is not None and current_proc_snap is not None
                and policy_snap is not None and proc_snap is not None
                and current_policy_snap.content_hash == policy_snap.content_hash
                and current_proc_snap.content_hash == proc_snap.content_hash
            )
            record(models.ValidationCheckType.HASH_MATCH, r.id, None, hash_ok,
                   "pinned content still matches the active version on both sides" if hash_ok
                   else "policy or procedure content has changed since this reference was last confirmed")
            if not hash_ok:
                _upsert_finding(
                    s, workspace_id, models.FindingType.OUTDATED_REFERENCE,
                    source_section_id=r.procedure_section_id, target_section_id=r.policy_section_id, reference_id=r.id,
                    description="Policy or procedure content has drifted since this reference was last confirmed valid.",
                )

            if r.status == models.ReferenceStatus.NEEDS_REVIEW:
                record(models.ValidationCheckType.LOW_CONFIDENCE_UNREVIEWED, r.id, None, False,
                       f"confidence {r.confidence} is below the auto-accept threshold and has not been human-reviewed")

            # 6. best-effort CONTRADICTION heuristic: numeric/time-unit phrases that disagree
            if current_policy_snap and current_proc_snap:
                policy_nums = _number_unit_phrases(current_policy_snap.content_text)
                proc_nums = _number_unit_phrases(current_proc_snap.content_text)
                if policy_nums and proc_nums and not (policy_nums & proc_nums):
                    record(models.ValidationCheckType.CONTRADICTION, r.id, None, False,
                           f"policy mentions {sorted(policy_nums)}, procedure mentions {sorted(proc_nums)} -- possible mismatch")
                    _upsert_finding(
                        s, workspace_id, models.FindingType.CONFLICT,
                        source_section_id=r.procedure_section_id, target_section_id=r.policy_section_id, reference_id=r.id,
                        description="Policy and procedure cite different numeric/time requirements for what looks like the same rule.",
                        evidence=f"policy: {sorted(policy_nums)} | procedure: {sorted(proc_nums)}",
                    )

        for c in checks:
            s.add(c)
        s.commit()

        passed_count = sum(1 for c in checks if c.passed)
        run.total_checks = len(checks)
        run.passed = passed_count
        run.failed = len(checks) - passed_count
        run.overall_status = "pass" if run.failed == 0 else "fail"
        s.add(run)
        s.commit()

        _log_event(
            s, workspace_id, models.ChangeEventType.VALIDATION_RUN,
            actor="system", description=f"Validation run: {passed_count}/{len(checks)} checks passed",
        )

        return {
            "validation_run_id": run.id,
            "overall_status": run.overall_status,
            "total_checks": run.total_checks,
            "passed": run.passed,
            "failed": run.failed,
            "checks": [
                {"check_type": c.check_type, "reference_id": c.reference_id, "section_id": c.section_id,
                 "passed": c.passed, "details": c.details}
                for c in checks
            ],
        }


@app.get("/workspaces/{workspace_id}/findings")
def list_findings(workspace_id: str, status: str | None = None):
    with Session(db.get_engine()) as s:
        query = select(models.Finding).where(models.Finding.workspace_id == workspace_id)
        if status:
            query = query.where(models.Finding.status == status)
        findings = s.exec(query.order_by(models.Finding.created_at.desc())).all()
        return [_finding_out(f) for f in findings]


# ============================================================================
# 9-11. maintenance loop
# ============================================================================


class UpdateRequestCreate(BaseModel):
    instruction: str


@app.post("/documents/{document_id}/update-requests")
def create_update_request(document_id: str, req: UpdateRequestCreate):
    """
    Works for both policies and procedures. Submits the instruction as a
    chat_async / ask_every_time job (so every edit, policy or procedure,
    goes through the same review gate) and creates a PENDING ProposedChange
    whose old_html/new_html are filled in once the job actually resolves
    (see GET .../proposed-changes below).
    """
    client = get_client()
    with Session(db.get_engine()) as s:
        doc = s.get(models.Document, document_id)
        if doc is None:
            raise HTTPException(404, "document not found")
        if not doc.active_version_id:
            raise HTTPException(409, "document has no active version yet")

        update_request = models.UpdateRequest(
            workspace_id=doc.workspace_id, document_id=doc.id,
            instruction_text=req.instruction, requested_by="human:compliance-officer",
        )
        s.add(update_request)
        s.commit()
        s.refresh(update_request)

        try:
            async_resp = client.chat_async(
                session_id=doc.superdocs_session_id, message=req.instruction, approval_mode="ask_every_time",
            )
        except SuperDocsError as e:
            update_request.status = models.UpdateRequestStatus.REJECTED
            s.add(update_request)
            s.commit()
            raise HTTPException(502, f"SuperDocs chat/async failed: {e}")

        proposed = models.ProposedChange(
            update_request_id=update_request.id, document_id=doc.id, section_id=None,
            base_version_id=doc.active_version_id, reference_id=None,
            superdocs_job_id=async_resp["job_id"],
        )
        s.add(proposed)

        update_request.status = models.UpdateRequestStatus.AWAITING_REVIEW
        s.add(update_request)
        s.commit()
        s.refresh(proposed)

        _log_event(
            s, doc.workspace_id, models.ChangeEventType.POLICY_EDIT_REQUESTED,
            document_id=doc.id, update_request_id=update_request.id, proposed_change_id=proposed.id,
            actor="human:compliance-officer", description=f"Update requested on {doc.title!r}: {req.instruction!r}",
        )

        return {"update_request": update_request.id, "proposed_change": _proposed_change_out(proposed)}


def _enrich_pending_change(client: SuperDocsClient, s: Session, pc: models.ProposedChange) -> None:
    """Poll SuperDocs for a PENDING ProposedChange with no diff yet and
    fill in old_html/new_html/ai_explanation/section_id once the job
    reaches awaiting_approval (or beyond).

    Previously this only handled the success path -- if the underlying
    SuperDocs job errored, got cancelled, or completed without ever
    producing a proposal, extract_pending_changes() just came back empty
    and this function silently returned, leaving the row PENDING with
    old_html still null forever. The Review screen has no other signal to
    go on, so that showed up as an infinite "Waiting on SuperDocs..."
    spinner with no way to tell a real failure apart from "still working".
    ProposedChangeStatus.FAILED exists in the model specifically for this
    case (see models.py) but nothing ever set it for an async-job failure
    discovered after the fact -- only for chat_async erroring immediately
    at submission time. Fixed below: a terminal non-success job status now
    actually flips the row to FAILED with a reason, instead of leaving it
    stuck.
    """
    if pc.old_html is not None or not pc.superdocs_job_id:
        return
    try:
        job = client.get_job(pc.superdocs_job_id)
    except SuperDocsError:
        return  # transient GET failure -- retry on the next poll, don't fail the row over a network blip

    status = job.get("status")

    if status in ("failed", "cancelled"):
        pc.status = models.ProposedChangeStatus.FAILED
        pc.ai_explanation = (
            job.get("error") or job.get("error_message") or job.get("message")
            or f"SuperDocs job ended with status={status!r} before producing a proposal to review."
        )
        s.add(pc)
        s.commit()
        return

    changes = client.extract_pending_changes(job)

    if not changes:
        if status == "completed":
            # The job ran to completion but never produced a diff -- e.g.
            # SuperDocs judged no change was actually needed. Surface that
            # as a terminal outcome rather than polling this row forever.
            pc.status = models.ProposedChangeStatus.FAILED
            pc.ai_explanation = "SuperDocs completed the job without proposing any change."
            s.add(pc)
            s.commit()
        return  # any other status (pending/running/etc) -- genuinely still in progress, check again next poll

    change = changes[0]
    pc.superdocs_change_id = change.change_id
    pc.old_html = change.old_html or ""
    pc.new_html = change.new_html or ""
    pc.ai_explanation = change.ai_explanation
    if change.chunk_id:
        # SuperDocs reports the chunk id it actually touched, which is
        # almost always a body chunk (a paragraph, a table row) rather
        # than the section's representative heading chunk -- a section's
        # content spans many chunk ids under real per-element SuperDocs
        # chunking, so resolve through SectionSnapshotChunk (every member
        # id), not just SectionSnapshot.chunk_id (one representative id).
        snap = s.exec(
            select(models.SectionSnapshot)
            .join(models.SectionSnapshotChunk, models.SectionSnapshotChunk.section_snapshot_id == models.SectionSnapshot.id)
            .where(
                models.SectionSnapshot.document_version_id == pc.base_version_id,
                models.SectionSnapshotChunk.chunk_id == change.chunk_id,
            )
        ).first()
        if snap:
            pc.section_id = snap.section_id
    s.add(pc)
    s.commit()


@app.get("/workspaces/{workspace_id}/proposed-changes")
def list_proposed_changes(workspace_id: str, status: str = "pending"):
    """
    The status filter is applied AFTER enrichment, not at query time.
    Enrichment can itself change a row's status mid-request now (a PENDING
    row discovered to have actually failed flips to FAILED right here --
    see _enrich_pending_change) -- filtering in SQL first would match a row
    against the status it had *before* that mutation, then serialize it
    with its now-different, no-longer-matching status. Fetching every
    change for the workspace and filtering in Python after enrichment
    keeps what's returned always consistent with what's actually in it.
    """
    client = get_client()
    with Session(db.get_engine()) as s:
        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()
        doc_ids = {d.id for d in docs}
        changes = s.exec(
            select(models.ProposedChange)
            .where(models.ProposedChange.document_id.in_(doc_ids))
            .order_by(models.ProposedChange.created_at.desc())
        ).all()
        for pc in changes:
            if pc.status == models.ProposedChangeStatus.PENDING:
                _enrich_pending_change(client, s, pc)
        if status:
            changes = [pc for pc in changes if pc.status == status]
        return [_proposed_change_out(pc) for pc in changes]


def _propagate_reference(
    client: SuperDocsClient, s: Session, ref: models.ProcedurePolicyReference,
    update_request_id: str, policy_section: models.Section, new_policy_text: str,
) -> models.ProposedChange:
    """One chat_async / ask_every_time job proposing an update to a
    procedure whose referenced policy section just changed. Mirrors the
    proven propagation pattern from the previous build."""
    proc_section = s.get(models.Section, ref.procedure_section_id)
    proc_doc = s.get(models.Document, proc_section.document_id)
    proc_snap = s.exec(
        select(models.SectionSnapshot).where(models.SectionSnapshot.id == ref.procedure_section_snapshot_id)
    ).first()

    message = (
        f"The policy section this procedure implements ('{policy_section.title}', "
        f"Policy §{policy_section.section_number}) was just updated. Its new wording is:\n\n"
        f"\"{new_policy_text}\"\n\n"
        f"Update the section \"{proc_section.title}\" of this procedure so it stays consistent "
        f"with the new policy wording -- for example, if a specific number, deadline, or "
        f"requirement changed in the policy text above, apply the equivalent change here. Only "
        f"edit what this specific policy change requires; do not rewrite unrelated content."
    )
    try:
        async_resp = client.chat_async(
            session_id=proc_doc.superdocs_session_id, message=message, approval_mode="ask_every_time",
        )
    except SuperDocsError as e:
        raise HTTPException(502, f"SuperDocs chat/async failed for {proc_doc.title}: {e}")

    proposed = models.ProposedChange(
        update_request_id=update_request_id, document_id=proc_doc.id, section_id=proc_section.id,
        base_version_id=proc_doc.active_version_id, reference_id=ref.id,
        superdocs_job_id=async_resp["job_id"],
    )
    s.add(proposed)

    ref.status = models.ReferenceStatus.STALE
    ref.updated_at = _now()
    s.add(ref)
    s.commit()
    s.refresh(proposed)

    _upsert_finding(
        s, proc_doc.workspace_id, models.FindingType.OUTDATED_REFERENCE,
        source_section_id=ref.procedure_section_id, target_section_id=ref.policy_section_id, reference_id=ref.id,
        description=f"{proc_doc.title!r} may be out of date after a change to Policy §{policy_section.section_number}.",
    )

    _log_event(
        s, proc_doc.workspace_id, models.ChangeEventType.PROCEDURE_CHANGE_PROPOSED,
        document_id=proc_doc.id, reference_id=ref.id, update_request_id=update_request_id, proposed_change_id=proposed.id,
        actor="system", description=f"Proposed update to {proc_doc.title!r} (job {async_resp['job_id']})",
    )
    return proposed


class ApproveRequest(BaseModel):
    approved: bool
    feedback: str | None = None


@app.post("/proposed-changes/{proposed_change_id}/approve")
def approve_proposed_change(proposed_change_id: str, req: ApproveRequest):
    client = get_client()
    with Session(db.get_engine()) as s:
        pc = s.get(models.ProposedChange, proposed_change_id)
        if pc is None:
            raise HTTPException(404, "proposed change not found")
        if pc.status != models.ProposedChangeStatus.PENDING:
            raise HTTPException(409, f"proposed change already resolved (status={pc.status})")

        _enrich_pending_change(client, s, pc)
        if pc.old_html is None:
            raise HTTPException(409, "SuperDocs job has not produced a proposal to review yet")

        doc = s.get(models.Document, pc.document_id)

        try:
            client.approve_change(
                session_id=doc.superdocs_session_id, job_id=pc.superdocs_job_id,
                change_id=pc.superdocs_change_id, approved=req.approved, feedback=req.feedback,
            )
            final_job = client.poll_job_until_done(pc.superdocs_job_id, timeout=120)
        except SuperDocsError as e:
            raise HTTPException(502, f"approval call failed: {e}")

        pc.status = models.ProposedChangeStatus.APPROVED if req.approved else models.ProposedChangeStatus.REJECTED
        pc.reviewed_by = "human:compliance-officer"
        pc.reviewed_at = _now()
        pc.feedback = req.feedback
        s.add(pc)
        s.commit()

        update_request = s.get(models.UpdateRequest, pc.update_request_id) if pc.update_request_id else None
        is_top_level = pc.reference_id is None

        propagated: list[dict] = []

        if req.approved:
            try:
                detail = client.get_document(doc.superdocs_document_id, include_html=True)
                full_html = detail.get("html", "") or ""
            except SuperDocsError as e:
                raise HTTPException(502, f"could not fetch updated document: {e}")

            version = _create_document_version(
                s, doc, normalized_html=full_html, source_format=models.SourceFormat.GENERATED,
                superdocs_version_id=(final_job.get("result") or {}).get("document_changes", {}).get("version_id"),
                change_summary=update_request.instruction_text if update_request else None,
                created_by="human:compliance-officer",
            )
            pc.resulting_version_id = version.id
            s.add(pc)
            s.commit()

            changed_sections = _sync_sections_for_version(s, doc, version)

            event_type = (
                models.ChangeEventType.POLICY_EDIT_APPROVED if doc.doc_type == models.DocType.POLICY
                else models.ChangeEventType.PROCEDURE_CHANGE_APPROVED
            )
            _log_event(
                s, doc.workspace_id, event_type, document_id=doc.id, document_version_id=version.id,
                update_request_id=pc.update_request_id, proposed_change_id=pc.id, approved=True,
                actor="human:compliance-officer", description=f"Approved update to {doc.title!r}",
            )

            if is_top_level and doc.doc_type == models.DocType.POLICY:
                # Fan out: find every reference whose policy section just changed, propagate.
                for sec in changed_sections:
                    refs = s.exec(
                        select(models.ProcedurePolicyReference).where(
                            models.ProcedurePolicyReference.policy_section_id == sec.id,
                            models.ProcedurePolicyReference.status.in_(
                                [models.ReferenceStatus.VALID, models.ReferenceStatus.NEEDS_REVIEW]
                            ),
                        )
                    ).all()
                    new_snap = s.exec(
                        select(models.SectionSnapshot)
                        .where(models.SectionSnapshot.section_id == sec.id, models.SectionSnapshot.document_version_id == version.id)
                    ).first()
                    for ref in refs:
                        try:
                            proc_pc = _propagate_reference(client, s, ref, pc.update_request_id, sec, new_snap.content_text if new_snap else "")
                            propagated.append({"reference_id": ref.id, "proposed_change_id": proc_pc.id})
                        except HTTPException:
                            continue  # one propagation failing shouldn't block the others

            elif pc.reference_id:
                # This was itself a propagated procedure edit -- resolve it.
                ref = s.get(models.ProcedurePolicyReference, pc.reference_id)
                if ref:
                    proc_section, proc_snap = next(
                        ((sec, snap) for sec, snap in _active_sections(s, doc) if sec.id == ref.procedure_section_id),
                        (None, None),
                    )
                    if proc_snap:
                        ref.procedure_section_snapshot_id = proc_snap.id
                        policy_sec = s.get(models.Section, ref.policy_section_id)
                        policy_doc = s.get(models.Document, policy_sec.document_id) if policy_sec else None
                        if policy_doc:
                            _, policy_snap_now = next(
                                ((sec, snap) for sec, snap in _active_sections(s, policy_doc) if sec.id == policy_sec.id),
                                (None, None),
                            )
                            if policy_snap_now:
                                ref.policy_section_snapshot_id = policy_snap_now.id
                    ref.status = models.ReferenceStatus.VALID
                    ref.updated_at = _now()
                    s.add(ref)
                    s.commit()

                    open_finding = s.exec(
                        select(models.Finding).where(
                            models.Finding.reference_id == ref.id, models.Finding.status == models.FindingStatus.OPEN
                        )
                    ).first()
                    if open_finding:
                        open_finding.status = models.FindingStatus.RESOLVED
                        open_finding.resolved_by_change_id = pc.id
                        open_finding.resolved_at = _now()
                        s.add(open_finding)
                        s.commit()
        else:
            event_type = (
                models.ChangeEventType.POLICY_EDIT_REJECTED if doc.doc_type == models.DocType.POLICY
                else models.ChangeEventType.PROCEDURE_CHANGE_REJECTED
            )
            _log_event(
                s, doc.workspace_id, event_type, document_id=doc.id,
                update_request_id=pc.update_request_id, proposed_change_id=pc.id, approved=False,
                actor="human:compliance-officer", description=f"Rejected update to {doc.title!r}" + (f" -- {req.feedback}" if req.feedback else ""),
            )
            if is_top_level:
                # STEP 28: reject the policy edit, nothing downstream ever happens.
                if update_request:
                    update_request.status = models.UpdateRequestStatus.REJECTED
                    update_request.resolved_at = _now()
                    s.add(update_request)
                    s.commit()

        if update_request and update_request.status not in (models.UpdateRequestStatus.REJECTED,):
            siblings = s.exec(
                select(models.ProposedChange).where(models.ProposedChange.update_request_id == update_request.id)
            ).all()
            if all(sib.status != models.ProposedChangeStatus.PENDING for sib in siblings):
                approved_count = sum(1 for sib in siblings if sib.status == models.ProposedChangeStatus.APPROVED)
                update_request.status = (
                    models.UpdateRequestStatus.APPROVED if approved_count == len(siblings)
                    else models.UpdateRequestStatus.PARTIALLY_APPROVED
                )
                update_request.resolved_at = _now()
                s.add(update_request)
                s.commit()

        s.refresh(pc)
        return {"proposed_change": _proposed_change_out(pc), "propagated": propagated}


# ============================================================================
# 12-13. reports
# ============================================================================


@app.post("/workspaces/{workspace_id}/reports")
def generate_report(workspace_id: str):
    with Session(db.get_engine()) as s:
        ws = s.get(models.Workspace, workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")

    validation = validate_workspace(workspace_id)

    with Session(db.get_engine()) as s:
        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()
        doc_ids = {d.id for d in docs}
        sections = s.exec(select(models.Section).where(models.Section.document_id.in_(doc_ids))).all()
        section_ids = {sec.id for sec in sections}
        references = s.exec(
            select(models.ProcedurePolicyReference).where(models.ProcedurePolicyReference.procedure_section_id.in_(section_ids))
        ).all()
        findings = s.exec(select(models.Finding).where(models.Finding.workspace_id == workspace_id)).all()
        pending = s.exec(
            select(models.ProposedChange).where(
                models.ProposedChange.document_id.in_(doc_ids), models.ProposedChange.status == models.ProposedChangeStatus.PENDING
            )
        ).all()

        prior_reports = s.exec(select(models.Report).where(models.Report.workspace_id == workspace_id)).all()
        pack_version_label = f"v1.{len(prior_reports)}"

        import json as _json
        summary = {
            "documents": len(docs),
            "policies": sum(1 for d in docs if d.doc_type == models.DocType.POLICY),
            "procedures": sum(1 for d in docs if d.doc_type == models.DocType.PROCEDURE),
            "references": len(references),
            "references_valid": sum(1 for r in references if r.status == models.ReferenceStatus.VALID),
            "references_stale": sum(1 for r in references if r.status == models.ReferenceStatus.STALE),
            "references_needs_review": sum(1 for r in references if r.status == models.ReferenceStatus.NEEDS_REVIEW),
            "findings_open": sum(1 for f in findings if f.status == models.FindingStatus.OPEN),
            "pending_reviews": len(pending),
            "validation_overall_status": validation["overall_status"],
        }

        report = models.Report(
            workspace_id=workspace_id, validation_run_id=validation["validation_run_id"],
            pack_version_label=pack_version_label, summary=_json.dumps(summary),
        )
        s.add(report)
        s.commit()
        s.refresh(report)

        _log_event(s, workspace_id, models.ChangeEventType.REPORT_GENERATED, actor="system",
                   description=f"Report {pack_version_label} generated")

        return {"id": report.id, "pack_version_label": report.pack_version_label,
                "generated_at": report.generated_at, "summary": summary}


@app.get("/workspaces/{workspace_id}/reports")
def list_reports(workspace_id: str):
    import json as _json
    with Session(db.get_engine()) as s:
        reports = s.exec(
            select(models.Report).where(models.Report.workspace_id == workspace_id).order_by(models.Report.generated_at.desc())
        ).all()
        return [
            {"id": r.id, "pack_version_label": r.pack_version_label, "generated_at": r.generated_at,
             "summary": _json.loads(r.summary)}
            for r in reports
        ]


# ============================================================================
# 14-15. export
# ============================================================================


def _content_disposition(title: str, extension: str) -> str:
    ascii_name = title.encode("ascii", "ignore").decode("ascii").strip() or "document"
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]", "", ascii_name).strip().replace(" ", "-") or "document"
    utf8_name = quote(f"{title}.{extension}")
    return f'attachment; filename="{ascii_name}.{extension}"; filename*=UTF-8\'\'{utf8_name}'


@app.get("/export/{document_id}")
def export_document(document_id: str, fmt: str = "docx"):
    client = get_client()
    with Session(db.get_engine()) as s:
        doc = s.get(models.Document, document_id)
        if doc is None:
            raise HTTPException(404, "document not found")
        try:
            file_bytes = client.export(session_id=doc.superdocs_session_id, fmt=fmt, filename=doc.title)
        except SuperDocsError as e:
            raise HTTPException(502, f"export failed: {e}")
        extension = "md" if fmt == "markdown" else fmt
        return Response(
            content=file_bytes,
            media_type=_EXPORT_CONTENT_TYPES.get(fmt, "application/octet-stream"),
            headers={"Content-Disposition": _content_disposition(doc.title, extension)},
        )


@app.get("/workspaces/{workspace_id}/export")
def export_workspace(workspace_id: str, fmt: str = "docx"):
    """Zips every document's ACTIVE version plus the latest report -- never
    a PROPOSED version, so an export can never accidentally ship an
    unapproved change."""
    client = get_client()
    with Session(db.get_engine()) as s:
        ws = s.get(models.Workspace, workspace_id)
        if ws is None:
            raise HTTPException(404, "workspace not found")
        docs = s.exec(select(models.Document).where(models.Document.workspace_id == workspace_id)).all()

        import json as _json
        latest_report = s.exec(
            select(models.Report).where(models.Report.workspace_id == workspace_id).order_by(models.Report.generated_at.desc())
        ).first()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            extension = "md" if fmt == "markdown" else fmt
            for doc in docs:
                if not doc.active_version_id:
                    continue
                try:
                    file_bytes = client.export(session_id=doc.superdocs_session_id, fmt=fmt, filename=doc.title)
                except SuperDocsError:
                    continue
                safe_name = re.sub(r"[^A-Za-z0-9._ -]", "", doc.title).strip().replace(" ", "-") or doc.id
                zf.writestr(f"{safe_name}.{extension}", file_bytes)
            if latest_report:
                zf.writestr(
                    "compliance-report.json",
                    _json.dumps(
                        {"pack_version_label": latest_report.pack_version_label,
                         "generated_at": latest_report.generated_at.isoformat(),
                         "summary": _json.loads(latest_report.summary)},
                        indent=2,
                    ),
                )

        _log_event(s, workspace_id, models.ChangeEventType.EXPORTED, actor="human", description=f"Workspace exported as {fmt}")

        buf.seek(0)
        return Response(
            content=buf.getvalue(), media_type="application/zip",
            headers={"Content-Disposition": _content_disposition(f"{ws.pack_name}", "zip")},
        )


# ============================================================================
# 16. audit log
# ============================================================================


@app.get("/workspaces/{workspace_id}/change-events")
def list_change_events(workspace_id: str):
    with Session(db.get_engine()) as s:
        events = s.exec(
            select(models.ChangeEvent).where(models.ChangeEvent.workspace_id == workspace_id).order_by(models.ChangeEvent.timestamp.desc())
        ).all()
        return [_event_out(e) for e in events]


@app.get("/health")
def health():
    return {"status": "ok"}
