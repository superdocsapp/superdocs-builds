"""ORM -> plain JSON-serializable dicts.

Kept explicit (rather than pydantic from_attributes) because these dicts are also
stored verbatim as idempotency replay bodies and sent as webhook payloads, so we
want full control over the shape and guaranteed JSON-native types.
"""

from __future__ import annotations

from app.db.models import Document, Job, ProposedChange


def document_to_dict(doc: Document) -> dict:
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "content_type": doc.content_type,
        "size_bytes": doc.size_bytes,
        "status": doc.status.value,
        "superdocs_document_id": doc.superdocs_document_id,
        "created_at": doc.created_at.isoformat(),
    }


def job_to_dict(job: Job) -> dict:
    return {
        "id": str(job.id),
        "type": job.type.value,
        "status": job.status.value,
        "document_id": str(job.document_id) if job.document_id else None,
        "ops_cost": job.ops_cost,
        "result": job.result,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def change_to_dict(change: ProposedChange) -> dict:
    return {
        "id": str(change.id),
        "job_id": str(change.job_id),
        "document_id": str(change.document_id),
        "chunk_id": change.chunk_id,
        "diff": change.diff,
        "status": change.status.value,
        "feedback": change.feedback,
        "created_at": change.created_at.isoformat(),
    }
