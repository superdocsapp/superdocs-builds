"""
HTTP layer. Auth here is deliberately minimal (an X-User-Id header) - see
README "What I cut": a real deployment sits behind the DMS's own SSO.

New in this revision: upload (create a new document from a real file),
version listing, version download, and discard-checkout.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, Header, HTTPException, Response, UploadFile

from app.dms.store import (
    DocumentLockedError,
    EthicalWallViolation,
    NotFoundError,
)
from app.models import (
    CheckinRequest,
    CheckinResponse,
    CheckoutResponse,
    DocumentSummary,
    EditRequest,
    EditResponse,
    PrecedentHit as PrecedentHitModel,
    PrecedentSearchResponse,
    ProposedChange,
    ReviewRequest,
    ReviewResponse,
    UploadDocumentResponse,
    VersionSummary,
)
from app.services.precedent_search import search_precedents
from app.services.workflow import CheckoutStateLostError, NotEditableError, UnresolvedChangesError
from app.superdocs.client import PendingChange

_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html",
    "txt": "text/plain",
    "md": "text/markdown",
}


def _translate_dms_error(exc: Exception) -> HTTPException:
    if isinstance(exc, EthicalWallViolation):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, DocumentLockedError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, NotEditableError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, CheckoutStateLostError):
        # 409, not 500: the request is well-formed, the server is healthy,
        # the checkout just can't be completed from here. The client's move
        # is discard-checkout and redo, which is a conflict-resolution step.
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, UnresolvedChangesError):
        # detail is structured, not a plain string: the client needs the
        # actual pending changes back to render them for one more review
        # round, not just an error message telling a human to go look.
        return HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "pending_changes": [
                    _to_proposed_change(c).model_dump() for c in exc.pending_changes
                ],
            },
        )
    return HTTPException(status_code=500, detail=str(exc))


def _to_proposed_change(change: PendingChange) -> ProposedChange:
    return ProposedChange(
        change_id=change.change_id,
        operation=change.operation,
        chunk_id=change.chunk_id,
        document_id=change.document_id,
        old_html=change.old_html,
        new_html=change.new_html,
        ai_explanation=change.ai_explanation,
    )


def register_routes(router: APIRouter, get_dms, get_superdocs, get_workflow) -> None:

    @router.post(
        "/matters/{matter_id}/documents",
        response_model=UploadDocumentResponse,
    )
    async def upload_document(
        matter_id: str,
        file: UploadFile = File(...),
        title: str | None = Form(None),
        user_id: str = Header(..., alias="X-User-Id"),
    ):
        workflow = get_workflow()
        file_bytes = await file.read()
        doc_title = title or file.filename or "Untitled document"
        try:
            doc = workflow.upload_new_document(
                matter_id=matter_id,
                user_id=user_id,
                title=doc_title,
                filename=file.filename or "upload.docx",
                file_bytes=file_bytes,
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        version = doc.current_version
        return UploadDocumentResponse(
            document_id=doc.document_id,
            matter_id=doc.matter_id,
            title=doc.title,
            version_number=version.version_number,
            byte_size=len(version.exported_bytes or b""),
        )

    @router.get("/matters/{matter_id}/documents", response_model=list[DocumentSummary])
    def list_documents(matter_id: str, user_id: str = Header(..., alias="X-User-Id")):
        dms = get_dms()
        try:
            docs = dms.list_documents(matter_id, user_id)
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        return [
            DocumentSummary(
                document_id=d.document_id,
                matter_id=d.matter_id,
                title=d.title,
                current_version=d.current_version.version_number,
                checked_out_by=d.checked_out_by,
            )
            for d in docs
        ]

    @router.get(
        "/matters/{matter_id}/documents/{document_id}/versions",
        response_model=list[VersionSummary],
    )
    def list_versions(
        matter_id: str, document_id: str, user_id: str = Header(..., alias="X-User-Id")
    ):
        dms = get_dms()
        try:
            versions = dms.list_versions(document_id, user_id)
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        return [
            VersionSummary(
                version_number=v.version_number,
                comment=v.comment,
                created_by=v.created_by,
                created_at=v.created_at.isoformat(),
                byte_size=len(v.exported_bytes or b""),
                has_exported_file=v.exported_bytes is not None,
            )
            for v in versions
        ]

    @router.get("/matters/{matter_id}/documents/{document_id}/versions/{version_number}/download")
    def download_version(
        matter_id: str,
        document_id: str,
        version_number: int,
        user_id: str = Header(..., alias="X-User-Id"),
    ):
        dms = get_dms()
        try:
            version = dms.get_version(document_id, version_number, user_id)
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        if version.exported_bytes is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Version {version_number} of document {document_id} has no exported "
                    "file - it predates the upload endpoint (seed/demo data), not an "
                    "approved edit."
                ),
            )
        media_type = _MEDIA_TYPES.get(version.exported_format or "", "application/octet-stream")
        filename = f"{document_id}-v{version_number}.{version.exported_format or 'bin'}"
        return Response(
            content=version.exported_bytes,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post(
        "/matters/{matter_id}/documents/{document_id}/checkout",
        response_model=CheckoutResponse,
    )
    def checkout(matter_id: str, document_id: str, user_id: str = Header(..., alias="X-User-Id")):
        workflow = get_workflow()
        try:
            doc, session_id = workflow.checkout(matter_id, document_id, user_id)
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        return CheckoutResponse(
            document_id=doc.document_id,
            matter_id=doc.matter_id,
            session_id=session_id,
            checked_out_by=user_id,
            version_loaded=doc.current_version.version_number,
            superdocs_chunks=0,
        )

    @router.post(
        "/matters/{matter_id}/documents/{document_id}/edit",
        response_model=EditResponse,
    )
    def request_edit(
        matter_id: str,
        document_id: str,
        body: EditRequest,
        user_id: str = Header(..., alias="X-User-Id"),
    ):
        workflow = get_workflow()
        try:
            proposal = workflow.propose_edit(
                document_id, user_id, body.instruction, model_tier=body.model_tier
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        return EditResponse(
            document_id=proposal.document_id,
            session_id=proposal.session_id,
            job_id=proposal.job_id,
            status=proposal.status,
            pending_changes=[_to_proposed_change(c) for c in proposal.pending_changes],
        )

    @router.post(
        "/matters/{matter_id}/documents/{document_id}/review",
        response_model=ReviewResponse,
    )
    def review(
        matter_id: str,
        document_id: str,
        body: ReviewRequest,
        user_id: str = Header(..., alias="X-User-Id"),
    ):
        workflow = get_workflow()
        decisions = [
            {"change_id": d.change_id, "approved": d.approved, "feedback": d.feedback}
            for d in body.decisions
        ]
        try:
            proposal = workflow.review_changes(document_id, user_id, body.job_id, decisions)
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        return ReviewResponse(
            document_id=proposal.document_id,
            session_id=proposal.session_id,
            job_id=proposal.job_id,
            status=proposal.status,
            remaining_pending_changes=[_to_proposed_change(c) for c in proposal.pending_changes],
        )

    @router.post(
        "/matters/{matter_id}/documents/{document_id}/checkin",
        response_model=CheckinResponse,
    )
    def checkin(
        matter_id: str,
        document_id: str,
        body: CheckinRequest,
        user_id: str = Header(..., alias="X-User-Id"),
    ):
        workflow = get_workflow()
        try:
            version = workflow.checkin(
                document_id, user_id, body.version_comment, body.metadata
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        return CheckinResponse(
            document_id=document_id,
            matter_id=matter_id,
            new_version=version.version_number,
            version_comment=version.comment,
            checked_in_by=user_id,
            byte_size=len(version.exported_bytes or b""),
        )

    @router.post("/matters/{matter_id}/documents/{document_id}/discard-checkout")
    def discard_checkout(
        matter_id: str, document_id: str, user_id: str = Header(..., alias="X-User-Id")
    ):
        workflow = get_workflow()
        try:
            workflow.discard_checkout(document_id, user_id)
        except Exception as exc:  # noqa: BLE001
            raise _translate_dms_error(exc)
        return {"document_id": document_id, "checked_out_by": None}

    @router.get(
        "/matters/{matter_id}/precedents",
        response_model=PrecedentSearchResponse,
    )
    def precedents(
        matter_id: str,
        q: str,
        user_id: str = Header(..., alias="X-User-Id"),
    ):
        dms = get_dms()
        hits = search_precedents(dms, user_id, q)
        return PrecedentSearchResponse(
            query=q,
            hits=[
                PrecedentHitModel(
                    document_id=h.document_id,
                    matter_id=h.matter_id,
                    title=h.title,
                    version=h.version,
                    score=h.score,
                    snippet=h.snippet,
                )
                for h in hits
            ],
            ai_summary=None,
        )